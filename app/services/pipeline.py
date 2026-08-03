from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiosqlite

from app import db as dbmod
from app.config import domains_config, get_settings
from app.services.conflict import check_conflict
from app.services.domain.factory import get_domain_provider
from app.services.filter import compact_key, filter_name
from app.services.generator import NameGenerator
from app.services.llm import LlmCredentials, LlmError, generate_names_from_brief
from app.services.pronunciation import pronounce_guide
from app.services.radio_test import radio_test
from app.services.scorer import score_candidate

logger = logging.getLogger(__name__)


async def generate_for_run(
    db: aiosqlite.Connection,
    run: dict[str, Any],
    *,
    llm_credentials: LlmCredentials | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    count = int(run["generate_count"])
    max_length = int(run["max_length"])
    brand_brief = (run.get("brand_brief") or "").strip()
    want_llm = bool(brand_brief and llm_credentials and llm_credentials.api_key)

    await dbmod.update_run_status(
        db,
        run["id"],
        "generating",
        {
            "phase": "generate",
            "target": count,
            "done": 0,
            "llm": "pending" if want_llm else ("skipped_no_key" if brand_brief else "skipped"),
        },
    )

    # 1) Local generation
    generator = NameGenerator()
    local = generator.generate(
        category=run["category"],
        keywords=run["keywords"],
        tone=run["tone"],
        max_length=max_length,
        count=count,
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
        )
        by_key[key] = {
            "name": cand.name,
            "pronunciation": cand.pronunciation or pronounce_guide(cand.name),
            "method": cand.method,
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

    # 2) Optional BYOK LLM generation from brand brief (merged, method=llm)
    llm_meta: dict[str, Any] = {
        "enabled": bool(brand_brief),
        "byok": bool(llm_credentials and llm_credentials.api_key),
        "directions": [],
        "count": 0,
        "error": None,
        "provider": None,
        "model": None,
    }
    if brand_brief and not (llm_credentials and llm_credentials.api_key):
        llm_meta["error"] = (
            "AI generation needs your own API key. Choose a provider, paste a key "
            "(stored only in this browser session), then generate again."
        )
    elif want_llm and llm_credentials:
        await dbmod.update_run_status(
            db,
            run["id"],
            "generating",
            {"phase": "llm", "target": count, "done": len(by_key), "llm": "running"},
        )
        try:
            llm_result = await generate_names_from_brief(
                category=run["category"],
                keywords=run["keywords"],
                tone=run["tone"],
                brand_brief=brand_brief,
                max_length=max_length,
                credentials=llm_credentials,
            )
            llm_meta["directions"] = llm_result.directions
            llm_meta["provider"] = llm_result.provider
            llm_meta["model"] = llm_result.model
            added = 0
            for item in llm_result.names:
                filt = filter_name(item.name, max_length=max_length)
                if not filt.ok:
                    continue
                key = compact_key(item.name)
                if not key:
                    continue
                scored = score_candidate(
                    item.name,
                    method="llm",
                    category=run["category"],
                    keywords=run["keywords"],
                    tone=run["tone"],
                )
                # LLM names win on collision so the brief is reflected in the table
                by_key[key] = {
                    "name": item.name,
                    "pronunciation": pronounce_guide(item.name),
                    "method": "llm",
                    "total_score": scored["total_score"],
                    "scores": scored["scores"],
                    "domains": {},
                    "conflict_level": "Not checked",
                    "conflict_notes": item.why or item.direction or "",
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
            llm_meta["error"] = None
        except LlmError as exc:
            logger.warning("LLM generation failed: %s", exc)
            llm_meta["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected LLM failure")
            llm_meta["error"] = f"Unexpected LLM failure: {type(exc).__name__}"

    rows = list(by_key.values())
    rows.sort(key=lambda r: (-float(r.get("total_score") or 0), r["name"]))

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

    await dbmod.upsert_candidates(db, run["id"], rows)

    # Persist LLM directions on the run settings blob
    run_settings = dict(run.get("settings") or {})
    run_settings["llm"] = {
        "directions": llm_meta.get("directions") or [],
        "count": llm_meta.get("count") or 0,
        "provider": llm_meta.get("provider"),
        "model": llm_meta.get("model"),
        "error": llm_meta.get("error"),
    }
    await dbmod.update_run_settings(db, run["id"], run_settings)

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
        "directions": llm_meta.get("directions") or [],
        "radio_tested": min(radio_top, len(rows)),
    }


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

        scored = score_candidate(
            candidate["name"],
            method=candidate["method"],
            category=run["category"],
            keywords=run["keywords"],
            tone=run["tone"],
            domains=domains,
            conflict_level=candidate.get("conflict_level", "Not checked"),
        )
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
        scored = score_candidate(
            c["name"],
            method=c["method"],
            category=run["category"],
            keywords=run["keywords"],
            tone=run["tone"],
            domains=c.get("domains") or {},
            conflict_level=result.level,
        )
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


def _slug(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())
