from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiosqlite

from app import db as dbmod
from app.config import domains_config, get_settings
from app.services.brand_quality import brand_quality_ok, credibility_score
from app.services.brief import direction_for_method
from app.services.conflict import check_conflict
from app.services.domain.factory import get_domain_provider
from app.services.filter import compact_key, filter_name
from app.services.generator import NameGenerator
from app.services.llm import LlmCredentials, LlmError, generate_names_from_brief
from app.services.naming_entity import get_naming_entity
from app.services.pronunciation import pronounce_guide
from app.services.preferences import build_preference_profile
from app.services.radio_test import radio_test
from app.services.real_words import is_real_word_candidate
from app.services.scorer import score_candidate
from app.services.favorite_signals import profile_from_signals
from app.services.naming_style import normalize_naming_style
from app.services.soft_invented import is_soft_invented
from app.services.trademark_screen import dataset_info, screen_name

logger = logging.getLogger(__name__)


async def generate_for_run(
    db: aiosqlite.Connection,
    run: dict[str, Any],
    *,
    llm_credentials: LlmCredentials | None = None,
    ai_requested: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    count = int(run["generate_count"])
    max_length = int(run["max_length"])
    brand_brief = (run.get("brand_brief") or "").strip()
    want_llm = bool(ai_requested and brand_brief and llm_credentials and llm_credentials.api_key)
    try:
        fav_profile = profile_from_signals(await dbmod.list_favorite_signals(db, limit=200))
    except Exception:  # noqa: BLE001
        fav_profile = None

    await dbmod.update_run_status(
        db,
        run["id"],
        "generating",
        {
            "phase": "generate",
            "target": count,
            "done": 0,
            "llm": "pending" if want_llm else "disabled",
        },
    )

    run_settings = run.get("settings") or {}
    naming_style = normalize_naming_style(str(run_settings.get("naming_style") or "invented"))
    brief = run_settings.get("brief") or {}
    naming_entity = str(brief.get("naming_entity") or "")
    entity = get_naming_entity(naming_entity)
    prefs = build_preference_profile(
        primary_language=str(brief.get("primary_language") or "en-global"),
        primary_language_other=str(brief.get("primary_language_other") or ""),
        audience=str(brief.get("audience") or ""),
        liked_brands=str(brief.get("liked_brands") or ""),
        avoid=str(brief.get("avoid") or ""),
    )

    # 1) Local generation. When AI is enabled the results are AI-only:
    # local coinages would dilute the model's output.
    local = []
    if not want_llm:
        generator = NameGenerator()
        local = generator.generate(
            category=run["category"],
            keywords=run["keywords"],
            tone=run["tone"],
            max_length=max_length,
            count=count,
            naming_style=naming_style,
            preferences=prefs,
        )

    by_key: dict[str, dict[str, Any]] = {}
    for cand in local:
        key = compact_key(cand.name)
        if not key:
            continue
        scored = score_candidate(
            cand.name,
            method=cand.method,
            category=run["category"],
            keywords=run["keywords"],
            tone=run["tone"],
            naming_style=naming_style,
            preferences=prefs,
            favorite_profile=fav_profile,
        )
        by_key[key] = {
            "name": cand.name,
            "pronunciation": cand.pronunciation or pronounce_guide(cand.name),
            "method": cand.method,
            "source": "local",
            "total_score": scored["total_score"],
            "scores": scored["scores"],
            "domains": {},
            "conflict_level": "Not checked",
            "conflict_notes": "",
            "rejected": False,
            "reject_reason": "",
            "favorite": False,
            "radio_score": None,
            "radio_pass": None,
            "radio_spellings": [],
            "radio_explanation": "",
            "radio_result": "",
        }

    # Tag local candidates with heuristic creative directions (no AI).
    for row in by_key.values():
        label, desc = direction_for_method(str(row.get("method") or ""))
        row["direction"] = label
        row["direction_description"] = desc

    # 2) Optional BYOK LLM: creative directions + names only
    llm_meta: dict[str, Any] = {
        "enabled": ai_requested,
        "requested": ai_requested,
        "byok": bool(llm_credentials and llm_credentials.api_key),
        "status": "pending" if want_llm else "disabled",
        "directions": [],
        "count": 0,
        "returned_count": 0,
        "accepted_count": 0,
        "error": None,
        "provider": llm_credentials.provider if llm_credentials else None,
        "model": llm_credentials.model if llm_credentials else None,
    }
    if ai_requested and not brand_brief:
        llm_meta["status"] = "failed"
        llm_meta["error"] = "AI generation requires a brand brief."
        await _persist_llm_meta(db, run, llm_meta)
        raise LlmError(llm_meta["error"])
    if ai_requested and not (llm_credentials and llm_credentials.api_key):
        llm_meta["status"] = "failed"
        llm_meta["error"] = "AI generation is enabled, but no API key was supplied."
        await _persist_llm_meta(db, run, llm_meta)
        raise LlmError(llm_meta["error"])
    # Quality > quantity: ask for a tight shortlist, not a padded dump.
    ai_target = max(8, min(count, 20))
    if want_llm and llm_credentials:
        llm_meta["target"] = ai_target
        await dbmod.update_run_status(
            db,
            run["id"],
            "generating",
            {"phase": "llm", "target": count, "done": len(by_key), "llm": "running"},
        )
        try:
            logger.info(
                "AI outbound request started provider=%s model=%s target=%s",
                llm_credentials.provider,
                llm_credentials.model,
                ai_target,
            )
            llm_result = await generate_names_from_brief(
                category=run["category"],
                keywords=run["keywords"],
                tone=run["tone"],
                brand_brief=brand_brief,
                naming_style=naming_style,
                naming_entity=naming_entity,
                liked_brands=str(brief.get("liked_brands") or ""),
                avoid=str(brief.get("avoid") or ""),
                max_length=max_length,
                credentials=llm_credentials,
                count=ai_target,
            )
            llm_meta["directions"] = llm_result.directions
            llm_meta["provider"] = llm_result.provider
            llm_meta["model"] = llm_result.model
            llm_meta["naming_entity"] = naming_entity
            llm_meta["returned_count"] = len(llm_result.names)
            added = 0
            rejected_soft = 0
            for item in llm_result.names:
                filt = filter_name(item.name, max_length=max_length, entity=entity)
                if not filt.ok:
                    continue
                key = compact_key(item.name)
                if not key:
                    continue
                if is_soft_invented(key):
                    rejected_soft += 1
                    continue
                # Hard-ban user avoid tokens / suffixes before scoring.
                avoid_hit = False
                for tok in prefs.avoid_tokens:
                    if len(tok) <= 2:
                        if key == tok or key.endswith(tok) or key.startswith(tok):
                            avoid_hit = True
                            break
                    elif tok in key:
                        avoid_hit = True
                        break
                if avoid_hit:
                    rejected_soft += 1
                    continue
                if "startup_suffix" in prefs.avoid_traits and key.endswith(("ly", "ify", "io")):
                    rejected_soft += 1
                    continue
                # Familiar style: prefer authentic words; allow strong compounds of real words.
                if naming_style == "real_word" and not is_real_word_candidate(key):
                    # Allow AI real words not in our curated list if they look commercially solid.
                    ok_rw, _ = brand_quality_ok(item.name, method="llm", min_score=70)
                    if not ok_rw:
                        rejected_soft += 1
                        continue
                else:
                    ok_q, _ = brand_quality_ok(item.name, method="llm", min_score=64)
                    if not ok_q:
                        rejected_soft += 1
                        continue
                scored = score_candidate(
                    item.name,
                    method="llm",
                    category=run["category"],
                    keywords=run["keywords"],
                    tone=run["tone"],
                    naming_style=naming_style,
                    preferences=prefs,
                    favorite_profile=fav_profile,
                )
                tier = (getattr(item, "tier", "") or "").strip().upper()
                total = float(scored["total_score"])
                if tier == "A":
                    total = min(100.0, total + 4.0)
                direction = (item.direction or "").strip() or "Creative AI directions"
                by_key[key] = {
                    "name": item.name,
                    "pronunciation": pronounce_guide(item.name),
                    "method": "llm",
                    "source": "ai",
                    "ai_provider": llm_result.provider,
                    "ai_model": llm_result.model,
                    "total_score": round(total, 1),
                    "scores": scored["scores"],
                    "domains": {},
                    "conflict_level": "Not checked",
                    "conflict_notes": item.why or "",
                    "direction": direction,
                    "direction_description": next(
                        (
                            str(d.get("description") or "")
                            for d in (llm_result.directions or [])
                            if str(d.get("name") or "").lower() == direction.lower()
                        ),
                        "Names brainstormed from your brief.",
                    ),
                    "rejected": False,
                    "reject_reason": "",
                    "favorite": False,
                    "radio_score": None,
                    "radio_pass": None,
                    "radio_spellings": [],
                    "radio_explanation": "",
                    "radio_result": "",
                }
                added += 1
            llm_meta["count"] = added
            llm_meta["accepted_count"] = added
            llm_meta["rejected_quality"] = rejected_soft
            llm_meta["error"] = None
            if added == 0:
                raise LlmError("AI returned no usable candidates after quality filtering.")
            llm_meta["status"] = "succeeded"
            logger.info(
                "AI outbound request succeeded provider=%s model=%s returned=%s accepted=%s",
                llm_meta["provider"],
                llm_meta["model"],
                llm_meta["returned_count"],
                added,
            )
        except LlmError as exc:
            logger.warning(
                "AI outbound request failed provider=%s model=%s error=%s",
                llm_meta.get("provider"),
                llm_meta.get("model"),
                exc,
            )
            llm_meta["status"] = "failed"
            llm_meta["error"] = str(exc)
            await _persist_llm_meta(db, run, llm_meta)
            await dbmod.update_run_status(
                db,
                run["id"],
                "ai_failed",
                {"phase": "llm", "llm": llm_meta},
            )
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected LLM failure")
            llm_meta["status"] = "failed"
            llm_meta["error"] = f"Unexpected LLM failure: {type(exc).__name__}"
            await _persist_llm_meta(db, run, llm_meta)
            await dbmod.update_run_status(
                db,
                run["id"],
                "ai_failed",
                {"phase": "llm", "llm": llm_meta},
            )
            raise LlmError(llm_meta["error"]) from None

    rows = list(by_key.values())
    # Hard quality cull: drop soft inventeds and low-credibility tails.
    culled: list[dict[str, Any]] = []
    for row in rows:
        key = compact_key(str(row.get("name") or ""))
        if not key or is_soft_invented(key):
            continue
        cred = float((row.get("scores") or {}).get("brand_credibility") or 0)
        if cred < 55 and credibility_score(str(row["name"]), method=str(row.get("method") or "")) < 55:
            continue
        culled.append(row)
    rows = culled or rows
    rows.sort(key=lambda r: (-float(r.get("total_score") or 0), r["name"]))
    # Keep a focused shortlist — quality over a padded dump.
    # Consultant shortlist: names a founder might actually consider.
    keep = max(12, min(count, 24))
    if len(rows) > keep:
        rows = rows[:keep]

    # 3) Radio test on top N
    radio_top = int(settings.radio_test_top)
    await dbmod.update_run_status(
        db,
        run["id"],
        "generating",
        {
            "phase": "radio_test",
            "target": min(radio_top, len(rows)),
            "done": 0,
            "llm": llm_meta,
        },
    )
    for i, row in enumerate(rows[:radio_top]):
        rt = radio_test(row["name"])
        row["pronunciation"] = rt.pronunciation or row.get("pronunciation") or ""
        row["radio_score"] = rt.score
        row["radio_pass"] = rt.passed
        row["radio_spellings"] = rt.alternate_spellings
        row["radio_explanation"] = rt.explanation
        row["radio_result"] = "pass" if rt.passed else "fail"
        if i and i % 25 == 0:
            await dbmod.update_run_status(
                db,
                run["id"],
                "generating",
                {
                    "phase": "radio_test",
                    "target": min(radio_top, len(rows)),
                    "done": i,
                    "llm": llm_meta,
                },
            )

    # Build display directions: LLM first, else heuristic buckets from local methods
    display_directions = list(llm_meta.get("directions") or [])
    if not display_directions:
        seen_dirs: dict[str, str] = {}
        for row in rows:
            label = str(row.get("direction") or "")
            if label and label not in seen_dirs:
                seen_dirs[label] = str(row.get("direction_description") or "")
        display_directions = [
            {"name": name, "description": desc} for name, desc in seen_dirs.items()
        ]
    llm_meta["directions"] = display_directions

    # Keep direction on scores blob for persistence without a schema migration
    for row in rows:
        scores = dict(row.get("scores") or {})
        scores["direction"] = row.get("direction") or ""
        scores["direction_description"] = row.get("direction_description") or ""
        scores["source"] = row.get("source") or (
            "ai" if row.get("method") == "llm" else "local"
        )
        if scores["source"] == "ai":
            scores["ai_provider"] = row.get("ai_provider") or llm_meta.get("provider") or ""
            scores["ai_model"] = row.get("ai_model") or llm_meta.get("model") or ""
        row["scores"] = scores

    await dbmod.upsert_candidates(db, run["id"], rows)

    await _persist_llm_meta(db, run, llm_meta)

    await dbmod.update_run_status(
        db,
        run["id"],
        "generated",
        {
            "phase": "generate",
            "target": count,
            "done": len(rows),
            "local": len(local),
            "llm": llm_meta,
            "radio_tested": min(radio_top, len(rows)),
        },
    )
    return {
        "generated": len(rows),
        "local": len(local),
        "llm": llm_meta.get("count") or 0,
        "llm_error": llm_meta.get("error"),
        "llm_note": llm_meta.get("note"),
        "ai": llm_meta,
        "directions": llm_meta.get("directions") or [],
        "radio_tested": min(radio_top, len(rows)),
    }


async def run_full_pipeline(
    db: aiosqlite.Connection,
    run: dict[str, Any],
    *,
    llm_credentials: LlmCredentials | None = None,
    ai_requested: bool = False,
) -> dict[str, Any]:
    """One-click: generate → score/radio → domains → conflicts → trademark screen."""
    gen = await generate_for_run(
        db,
        run,
        llm_credentials=llm_credentials,
        ai_requested=ai_requested,
    )
    run = await dbmod.get_run(db, run["id"]) or run
    domains = {"checked": 0, "skipped": 0}
    conflicts = {"checked": 0}
    run_settings = run.get("settings") or {}
    if int(run_settings.get("domain_check_top") or 0) > 0:
        domains = await check_domains_for_run(db, run)
        run = await dbmod.get_run(db, run["id"]) or run
    if int(run_settings.get("conflict_check_top") or 0) > 0:
        conflicts = await check_conflicts_for_run(db, run)
        run = await dbmod.get_run(db, run["id"]) or run
    trademarks = await check_trademarks_for_run(db, run)
    return {
        **gen,
        "domains": domains,
        "conflicts": conflicts,
        "trademarks": trademarks,
    }


async def check_trademarks_for_run(
    db: aiosqlite.Connection,
    run: dict[str, Any],
    *,
    top_n: int | None = None,
) -> dict[str, Any]:
    """Deterministic USPTO-data trademark screening for the top candidates."""
    run_settings = run.get("settings") or {}
    n = top_n if top_n is not None else int(run_settings.get("trademark_check_top") or 40)
    candidates = await dbmod.list_candidates(db, run["id"], include_rejected=False)
    candidates = candidates[:n]

    await dbmod.update_run_status(
        db,
        run["id"],
        "checking_trademarks",
        {"phase": "trademarks", "target": len(candidates), "done": 0},
    )

    counts = {"low": 0, "medium": 0, "high": 0}
    done = 0
    for c in candidates:
        result = screen_name(
            c["name"],
            category=run["category"],
            keywords=run["keywords"],
        )
        counts[result.risk] = counts.get(result.risk, 0) + 1
        await dbmod.update_candidate_trademark(
            db,
            run["id"],
            c["name"],
            risk=result.risk,
            summary=result.summary,
            reason=result.reason,
            matches=[m.to_dict() for m in result.matches],
        )
        done += 1

    await dbmod.update_run_status(
        db,
        run["id"],
        "ready",
        {"phase": "trademarks", "target": len(candidates), "done": done},
    )
    return {"checked": done, **counts, "dataset": dataset_info()}


async def check_domains_for_run(
    db: aiosqlite.Connection,
    run: dict[str, Any],
    *,
    top_n: int | None = None,
    resume: bool = True,
) -> dict[str, Any]:
    settings = get_settings()
    run_settings = run.get("settings") or {}
    n = top_n if top_n is not None else int(run_settings.get("domain_check_top", 200))
    extensions = run["extensions"]
    cache_ttl = int((domains_config().get("cache_ttl_hours") or 168))

    candidates = await dbmod.list_candidates(db, run["id"], include_rejected=False)
    candidates = candidates[:n]

    todo = []
    for c in candidates:
        domains = c.get("domains") or {}
        if resume and extensions and all(
            ext in domains and domains[ext].get("status") not in {None, "", "error"}
            for ext in extensions
        ):
            continue
        todo.append(c)

    total = len(todo)
    await dbmod.update_run_status(
        db,
        run["id"],
        "checking_domains",
        {"phase": "domains", "target": total, "done": 0},
    )

    provider = get_domain_provider()
    sem = asyncio.Semaphore(settings.domain_check_concurrency)
    done = 0

    async def check_one(candidate: dict[str, Any]) -> None:
        nonlocal done
        domains = dict(candidate.get("domains") or {})
        async with sem:
            for ext in extensions:
                if resume and ext in domains and domains[ext].get("status") not in {None, "", "error"}:
                    continue
                fqdn = f"{_slug(candidate['name'])}{ext}"
                cached = await dbmod.get_domain_cache(db, fqdn, cache_ttl)
                if cached:
                    result = {
                        "domain": cached["domain"],
                        "status": cached["status"],
                        "detail": cached["detail"],
                        "premium": cached["premium"],
                        "cached": True,
                    }
                else:
                    rd = await provider.check_domain(fqdn)
                    result = rd.to_dict()
                    await dbmod.set_domain_cache(
                        db,
                        domain=rd.domain,
                        status=rd.status,
                        detail=rd.detail,
                        premium=rd.premium,
                        raw=rd.raw,
                    )
                domains[ext] = result

        rs = run.get("settings") or {}
        br = rs.get("brief") or {}
        scored = score_candidate(
            candidate["name"],
            method=candidate["method"],
            category=run["category"],
            keywords=run["keywords"],
            tone=run["tone"],
            domains=domains,
            conflict_level=candidate.get("conflict_level", "Not checked"),
            naming_style=normalize_naming_style(str(rs.get("naming_style") or "invented")),
            preferences=build_preference_profile(
                primary_language=str(br.get("primary_language") or "en-global"),
                primary_language_other=str(br.get("primary_language_other") or ""),
                audience=str(br.get("audience") or ""),
                liked_brands=str(br.get("liked_brands") or ""),
                avoid=str(br.get("avoid") or ""),
            ),
        )
        _preserve_direction(candidate, scored["scores"])
        await dbmod.update_candidate_domains(
            db,
            run["id"],
            candidate["name"],
            domains,
            total_score=scored["total_score"],
            scores=scored["scores"],
        )
        done += 1
        if done % 5 == 0 or done == total:
            await dbmod.update_run_status(
                db,
                run["id"],
                "checking_domains",
                {"phase": "domains", "target": total, "done": done},
            )

    try:
        await asyncio.gather(*(check_one(c) for c in todo))
    finally:
        close = getattr(provider, "aclose", None)
        if close:
            await close()

    await dbmod.update_run_status(
        db,
        run["id"],
        "domains_done",
        {"phase": "domains", "target": total, "done": done},
    )
    return {"checked": done, "skipped": len(candidates) - total}


async def check_conflicts_for_run(
    db: aiosqlite.Connection,
    run: dict[str, Any],
    *,
    top_n: int | None = None,
) -> dict[str, Any]:
    run_settings = run.get("settings") or {}
    n = top_n if top_n is not None else int(run_settings.get("conflict_check_top", 50))
    candidates = await dbmod.list_candidates(db, run["id"], include_rejected=False)
    candidates = candidates[:n]

    await dbmod.update_run_status(
        db,
        run["id"],
        "checking_conflicts",
        {"phase": "conflicts", "target": len(candidates), "done": 0},
    )

    done = 0
    for c in candidates:
        result = check_conflict(c["name"], category=run["category"])
        rs = run.get("settings") or {}
        br = rs.get("brief") or {}
        scored = score_candidate(
            c["name"],
            method=c["method"],
            category=run["category"],
            keywords=run["keywords"],
            tone=run["tone"],
            domains=c.get("domains") or {},
            conflict_level=result.level,
            naming_style=normalize_naming_style(str(rs.get("naming_style") or "invented")),
            preferences=build_preference_profile(
                primary_language=str(br.get("primary_language") or "en-global"),
                primary_language_other=str(br.get("primary_language_other") or ""),
                audience=str(br.get("audience") or ""),
                liked_brands=str(br.get("liked_brands") or ""),
                avoid=str(br.get("avoid") or ""),
            ),
        )
        _preserve_direction(c, scored["scores"])
        await dbmod.update_candidate_conflict(
            db,
            run["id"],
            c["name"],
            result.level,
            result.notes,
            total_score=scored["total_score"],
            scores=scored["scores"],
        )
        done += 1

    await dbmod.update_run_status(
        db,
        run["id"],
        "ready",
        {"phase": "conflicts", "target": len(candidates), "done": done},
    )
    return {"checked": done}


def _preserve_direction(candidate: dict[str, Any], scores: dict[str, Any]) -> None:
    """Re-scoring rebuilds the scores blob; keep the direction tags stored in it."""
    old = candidate.get("scores") or {}
    for key in ("direction", "direction_description", "source", "ai_provider", "ai_model"):
        if old.get(key) and not scores.get(key):
            scores[key] = old[key]


async def _persist_llm_meta(
    db: aiosqlite.Connection,
    run: dict[str, Any],
    llm_meta: dict[str, Any],
) -> None:
    """Persist safe AI diagnostics. Credentials are never included."""
    settings = dict(run.get("settings") or {})
    settings["llm"] = {
        "enabled": bool(llm_meta.get("enabled")),
        "requested": bool(llm_meta.get("requested")),
        "status": llm_meta.get("status") or "disabled",
        "directions": llm_meta.get("directions") or [],
        "count": int(llm_meta.get("count") or 0),
        "returned_count": int(llm_meta.get("returned_count") or 0),
        "accepted_count": int(llm_meta.get("accepted_count") or 0),
        "target": int(llm_meta.get("target") or 0),
        "ai_only": bool(llm_meta.get("requested")),
        "provider": llm_meta.get("provider"),
        "model": llm_meta.get("model"),
        "error": llm_meta.get("error"),
        "note": llm_meta.get("note"),
    }
    await dbmod.update_run_settings(db, run["id"], settings)


def _slug(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())
