from __future__ import annotations

import csv
import io
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app import db as dbmod
from app.config import domains_config, scoring_config
from app.schemas import (
    ConflictCheckRequest,
    DomainCheckRequest,
    FavoriteRequest,
    RunCreate,
    TrademarkCheckRequest,
)
from app.services.llm import LlmError, resolve_credentials
from app.services.pipeline import (
    check_conflicts_for_run,
    check_domains_for_run,
    check_trademarks_for_run,
    generate_for_run,
    run_full_pipeline,
)

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _db(request: Request):
    return request.app.state.db


def _llm_credentials_from_request(request: Request):
    """
    Ephemeral BYOK credentials from headers only.
    Never accepted via query string. Never written to the database.
    """
    try:
        return resolve_credentials(
            request_provider=request.headers.get("X-LLM-Provider"),
            request_api_key=request.headers.get("X-LLM-API-Key"),
            request_model=request.headers.get("X-LLM-Model"),
        )
    except LlmError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _ai_requested(request: Request) -> bool:
    enabled = (request.headers.get("X-LLM-Enabled") or "").strip().lower()
    if enabled in {"false", "0", "no", "off"}:
        return False
    if enabled in {"true", "1", "yes", "on"}:
        return True
    # Backward compatibility: supplying a key explicitly requests AI.
    return bool((request.headers.get("X-LLM-API-Key") or "").strip())


@router.post("")
async def create_run(payload: RunCreate, request: Request) -> dict[str, Any]:
    db = _db(request)
    run_id = uuid.uuid4().hex[:12]
    defaults = domains_config().get("default_extensions") or [".com", ".app", ".co"]
    extensions = payload.extensions or defaults
    settings = {
        "domain_check_top": payload.domain_check_top,
        "conflict_check_top": payload.conflict_check_top,
        "trademark_check_top": payload.trademark_check_top,
        "radio_test_top": payload.radio_test_top,
        "naming_style": payload.naming_style,
        "scoring": scoring_config(),
        "brief": {
            "problem": payload.problem,
            "building": payload.problem,  # legacy alias for older clients
            "naming_entity": payload.naming_entity,
            "audience": payload.audience,
            "liked_brands": payload.liked_brands,
            "avoid": payload.avoid,
            "primary_language": payload.primary_language,
            "primary_language_other": payload.primary_language_other,
        },
    }
    run = await dbmod.create_run(
        db,
        run_id=run_id,
        category=payload.category.strip(),
        keywords=payload.keywords,
        tone=payload.tone.strip(),
        brand_brief=(payload.brand_brief or "").strip(),
        max_length=payload.max_length,
        extensions=extensions,
        generate_count=payload.generate_count,
        settings=settings,
    )
    if not payload.run_pipeline:
        return {"run": _public_run(run)}

    credentials = _llm_credentials_from_request(request)
    try:
        result = await run_full_pipeline(
            db,
            run,
            llm_credentials=credentials,
            ai_requested=_ai_requested(request),
        )
    except LlmError as exc:
        raise HTTPException(status_code=502, detail=f"AI generation failed: {exc}") from exc
    run = await dbmod.get_run(db, run_id)
    candidates = await dbmod.list_candidates(db, run_id, include_rejected=False)
    return {
        "run": _public_run(run),
        "result": result,
        "candidates": [_public_candidate(c) for c in candidates],
    }


@router.get("")
async def list_runs(request: Request) -> dict[str, Any]:
    db = _db(request)
    runs = await dbmod.list_runs(db)
    return {"runs": [_public_run(r) for r in runs]}


@router.get("/{run_id}")
async def get_run(
    run_id: str,
    request: Request,
    include_rejected: bool = Query(default=False),
) -> dict[str, Any]:
    db = _db(request)
    run = await dbmod.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    candidates = await dbmod.list_candidates(db, run_id, include_rejected=include_rejected)
    return {"run": _public_run(run), "candidates": [_public_candidate(c) for c in candidates]}


@router.post("/{run_id}/generate")
async def generate(run_id: str, request: Request) -> dict[str, Any]:
    db = _db(request)
    run = await dbmod.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    credentials = _llm_credentials_from_request(request)
    try:
        result = await generate_for_run(
            db,
            run,
            llm_credentials=credentials,
            ai_requested=_ai_requested(request),
        )
    except LlmError as exc:
        raise HTTPException(status_code=502, detail=f"AI generation failed: {exc}") from exc
    run = await dbmod.get_run(db, run_id)
    return {"ok": True, "result": result, "run": _public_run(run)}


@router.post("/{run_id}/check-domains")
async def check_domains(
    run_id: str,
    request: Request,
    payload: DomainCheckRequest | None = None,
) -> dict[str, Any]:
    db = _db(request)
    run = await dbmod.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    body = payload or DomainCheckRequest()
    result = await check_domains_for_run(
        db,
        run,
        top_n=body.top_n,
        resume=body.resume,
    )
    run = await dbmod.get_run(db, run_id)
    return {"ok": True, "result": result, "run": _public_run(run)}


@router.post("/{run_id}/check-conflicts")
async def check_conflicts(
    run_id: str,
    request: Request,
    payload: ConflictCheckRequest | None = None,
) -> dict[str, Any]:
    db = _db(request)
    run = await dbmod.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    body = payload or ConflictCheckRequest()
    result = await check_conflicts_for_run(db, run, top_n=body.top_n)
    run = await dbmod.get_run(db, run_id)
    return {"ok": True, "result": result, "run": _public_run(run)}


@router.post("/{run_id}/check-trademarks")
async def check_trademarks(
    run_id: str,
    request: Request,
    payload: TrademarkCheckRequest | None = None,
) -> dict[str, Any]:
    db = _db(request)
    run = await dbmod.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    body = payload or TrademarkCheckRequest()
    result = await check_trademarks_for_run(db, run, top_n=body.top_n)
    run = await dbmod.get_run(db, run_id)
    return {"ok": True, "result": result, "run": _public_run(run)}


@router.post("/{run_id}/favorite")
async def favorite(run_id: str, payload: FavoriteRequest, request: Request) -> dict[str, Any]:
    db = _db(request)
    run = await dbmod.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    name = payload.name.strip()
    ok = await dbmod.set_favorite(db, run_id, name, payload.favorite)
    if not ok:
        raise HTTPException(status_code=404, detail="Candidate not found")
    # Learn from what founders keep — anonymized shape signals only.
    try:
        from app.services.favorite_signals import signal_from_name

        cands = await dbmod.list_candidates(db, run_id, include_rejected=True)
        hit = next((c for c in cands if c.get("name") == name), None)
        settings = run.get("settings") or {}
        sig = signal_from_name(
            name,
            method=str((hit or {}).get("method") or ""),
            naming_style=str(settings.get("naming_style") or ""),
        )
        await dbmod.record_favorite_signal(
            db,
            name_key=sig["key"],
            length=int(sig["length"]),
            shape=str(sig["shape"]),
            method=str(sig["method"]),
            naming_style=str(sig["naming_style"]),
            ends_vowel=bool(sig["ends_vowel"]),
            active=bool(payload.favorite),
        )
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "name": payload.name, "favorite": payload.favorite}


@router.get("/{run_id}/export.csv")
async def export_csv(
    run_id: str,
    request: Request,
    include_rejected: bool = Query(default=False),
) -> StreamingResponse:
    db = _db(request)
    run = await dbmod.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    candidates = await dbmod.list_candidates(db, run_id, include_rejected=include_rejected)
    extensions = run["extensions"]

    output = io.StringIO()
    writer = csv.writer(output)
    header = [
        "name",
        "pronunciation",
        "total_score",
        "pronounceability",
        "spelling_clarity",
        "memorability",
        "category_relevance",
        "brand_flexibility",
        "domain_availability",
        "length_score",
        "conflict_level",
        "conflict_notes",
        "trademark_risk",
        "trademark_summary",
        "trademark_reason",
        "generation_source",
        "radio_score",
        "radio_result",
        "radio_spellings",
        "radio_explanation",
        "favorite",
    ]
    for ext in extensions:
        header.append(f"{ext}_status")
    writer.writerow(header)

    for c in candidates:
        scores = c.get("scores") or {}
        domains = c.get("domains") or {}
        spellings = c.get("radio_spellings") or []
        row = [
            _csv_safe(c["name"]),
            _csv_safe(c.get("pronunciation", "")),
            c.get("total_score", 0),
            scores.get("pronounceability", ""),
            scores.get("spelling_clarity", ""),
            scores.get("memorability", ""),
            scores.get("category_relevance", ""),
            scores.get("brand_flexibility", ""),
            scores.get("domain_availability", ""),
            scores.get("length", ""),
            _csv_safe(c.get("conflict_level", "")),
            _csv_safe(c.get("conflict_notes", "")),
            _csv_safe(c.get("trademark_risk", "")),
            _csv_safe(c.get("trademark_summary", "")),
            _csv_safe(c.get("trademark_reason", "")),
            _csv_safe("ai" if c.get("method") == "llm" else "local"),
            c.get("radio_score") if c.get("radio_score") is not None else "",
            _csv_safe(c.get("radio_result", "")),
            _csv_safe("; ".join(spellings)),
            _csv_safe(c.get("radio_explanation", "")),
            "yes" if c.get("favorite") else "no",
        ]
        for ext in extensions:
            status = (domains.get(ext) or {}).get("status", "")
            row.append(_csv_safe(status))
        writer.writerow(row)

    output.seek(0)
    filename = f"names-{run_id}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _public_run(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if not run:
        return None
    settings = run.get("settings") or {}
    brief = settings.get("brief") or {}
    return {
        "id": run["id"],
        "created_at": run["created_at"],
        "category": run["category"],
        "keywords": run["keywords"],
        "tone": run["tone"],
        "brand_brief": run.get("brand_brief") or "",
        "problem": brief.get("problem") or brief.get("building") or run["category"],
        "building": brief.get("problem") or brief.get("building") or run["category"],
        "naming_entity": brief.get("naming_entity") or "",
        "audience": brief.get("audience") or "",
        "liked_brands": brief.get("liked_brands") or "",
        "avoid": brief.get("avoid") or "",
        "primary_language": brief.get("primary_language")
        or brief.get("primary_market")
        or "en-global",
        "primary_language_other": brief.get("primary_language_other")
        or brief.get("primary_market_other")
        or "",
        "naming_style": settings.get("naming_style") or "invented",
        "max_length": run["max_length"],
        "extensions": run["extensions"],
        "generate_count": run["generate_count"],
        "status": run["status"],
        "progress": run.get("progress") or {},
        "llm": settings.get("llm") or {},
        "settings": {
            "domain_check_top": settings.get("domain_check_top"),
            "conflict_check_top": settings.get("conflict_check_top"),
            "trademark_check_top": settings.get("trademark_check_top"),
            "radio_test_top": settings.get("radio_test_top"),
            "naming_style": settings.get("naming_style") or "invented",
        },
    }


def _public_candidate(c: dict[str, Any]) -> dict[str, Any]:
    scores = c.get("scores") or {}
    source = scores.get("source") or ("ai" if c.get("method") == "llm" else "local")
    return {
        "name": c["name"],
        "pronunciation": c.get("pronunciation", ""),
        "total_score": c.get("total_score", 0),
        "scores": scores,
        "domains": c.get("domains") or {},
        "conflict_level": c.get("conflict_level", "Not checked"),
        "conflict_notes": c.get("conflict_notes", ""),
        "trademark_risk": c.get("trademark_risk", ""),
        "trademark_summary": c.get("trademark_summary", ""),
        "trademark_reason": c.get("trademark_reason", ""),
        "trademark_matches": c.get("trademark_matches") or [],
        "direction": scores.get("direction") or c.get("direction") or "",
        "direction_description": scores.get("direction_description")
        or c.get("direction_description")
        or "",
        "method": c.get("method", ""),
        "source": source,
        "generation_source": source,
        "ai_provider": scores.get("ai_provider") or "",
        "ai_model": scores.get("ai_model") or "",
        "radio_score": c.get("radio_score"),
        "radio_pass": c.get("radio_pass"),
        "radio_result": c.get("radio_result") or "",
        "radio_spellings": c.get("radio_spellings") or [],
        "radio_explanation": c.get("radio_explanation") or "",
        "favorite": bool(c.get("favorite")),
        "rejected": bool(c.get("rejected")),
    }


def _csv_safe(value: Any) -> str:
    text = str(value if value is not None else "")
    if text.startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text
