from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.config import get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    category TEXT NOT NULL,
    keywords TEXT NOT NULL,
    tone TEXT NOT NULL,
    brand_brief TEXT NOT NULL DEFAULT '',
    max_length INTEGER NOT NULL,
    extensions TEXT NOT NULL,
    generate_count INTEGER NOT NULL,
    settings_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    progress_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    name TEXT NOT NULL,
    pronunciation TEXT NOT NULL,
    method TEXT NOT NULL,
    total_score REAL NOT NULL DEFAULT 0,
    scores_json TEXT NOT NULL DEFAULT '{}',
    domains_json TEXT NOT NULL DEFAULT '{}',
    conflict_level TEXT NOT NULL DEFAULT 'Not checked',
    conflict_notes TEXT NOT NULL DEFAULT '',
    rejected INTEGER NOT NULL DEFAULT 0,
    reject_reason TEXT NOT NULL DEFAULT '',
    favorite INTEGER NOT NULL DEFAULT 0,
    radio_score REAL,
    radio_pass INTEGER,
    radio_spellings TEXT NOT NULL DEFAULT '[]',
    radio_explanation TEXT NOT NULL DEFAULT '',
    radio_result TEXT NOT NULL DEFAULT '',
    trademark_risk TEXT NOT NULL DEFAULT '',
    trademark_summary TEXT NOT NULL DEFAULT '',
    trademark_reason TEXT NOT NULL DEFAULT '',
    trademark_matches TEXT NOT NULL DEFAULT '[]',
    UNIQUE(run_id, name),
    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_candidates_run ON candidates(run_id);
CREATE INDEX IF NOT EXISTS idx_candidates_score ON candidates(run_id, total_score DESC);

CREATE TABLE IF NOT EXISTS domain_cache (
    domain TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    premium INTEGER NOT NULL DEFAULT 0,
    checked_at TEXT NOT NULL,
    raw_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS favorite_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    name_key TEXT NOT NULL,
    length INTEGER NOT NULL,
    shape TEXT NOT NULL,
    method TEXT NOT NULL DEFAULT '',
    naming_style TEXT NOT NULL DEFAULT '',
    ends_vowel INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_favorite_signals_active ON favorite_signals(active, created_at DESC);
"""

MIGRATIONS = [
    ("brand_brief", "ALTER TABLE runs ADD COLUMN brand_brief TEXT NOT NULL DEFAULT ''"),
    ("radio_score", "ALTER TABLE candidates ADD COLUMN radio_score REAL"),
    ("radio_pass", "ALTER TABLE candidates ADD COLUMN radio_pass INTEGER"),
    ("radio_spellings", "ALTER TABLE candidates ADD COLUMN radio_spellings TEXT NOT NULL DEFAULT '[]'"),
    ("radio_explanation", "ALTER TABLE candidates ADD COLUMN radio_explanation TEXT NOT NULL DEFAULT ''"),
    ("radio_result", "ALTER TABLE candidates ADD COLUMN radio_result TEXT NOT NULL DEFAULT ''"),
    ("trademark_risk", "ALTER TABLE candidates ADD COLUMN trademark_risk TEXT NOT NULL DEFAULT ''"),
    ("trademark_summary", "ALTER TABLE candidates ADD COLUMN trademark_summary TEXT NOT NULL DEFAULT ''"),
    ("trademark_reason", "ALTER TABLE candidates ADD COLUMN trademark_reason TEXT NOT NULL DEFAULT ''"),
    ("trademark_matches", "ALTER TABLE candidates ADD COLUMN trademark_matches TEXT NOT NULL DEFAULT '[]'"),
    (
        "favorite_signals",
        """
        CREATE TABLE IF NOT EXISTS favorite_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            name_key TEXT NOT NULL,
            length INTEGER NOT NULL,
            shape TEXT NOT NULL,
            method TEXT NOT NULL DEFAULT '',
            naming_style TEXT NOT NULL DEFAULT '',
            ends_vowel INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        )
        """,
    ),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def connect() -> aiosqlite.Connection:
    settings = get_settings()
    db = await aiosqlite.connect(settings.db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    await db.executescript(SCHEMA)
    await _migrate(db)
    await db.commit()
    return db


async def _migrate(db: aiosqlite.Connection) -> None:
    """Add columns introduced after the first schema (safe on existing DBs)."""
    cur = await db.execute("PRAGMA table_info(runs)")
    run_cols = {row[1] for row in await cur.fetchall()}
    cur = await db.execute("PRAGMA table_info(candidates)")
    cand_cols = {row[1] for row in await cur.fetchall()}
    for name, sql in MIGRATIONS:
        if name == "brand_brief" and name not in run_cols:
            await db.execute(sql)
        elif name != "brand_brief" and name not in cand_cols:
            await db.execute(sql)


def row_to_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def loads(text: str, default: Any = None) -> Any:
    if not text:
        return default
    return json.loads(text)


async def create_run(
    db: aiosqlite.Connection,
    *,
    run_id: str,
    category: str,
    keywords: list[str],
    tone: str,
    brand_brief: str,
    max_length: int,
    extensions: list[str],
    generate_count: int,
    settings: dict[str, Any],
) -> dict[str, Any]:
    await db.execute(
        """
        INSERT INTO runs (
            id, created_at, category, keywords, tone, brand_brief, max_length,
            extensions, generate_count, settings_json, status, progress_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'created', '{}')
        """,
        (
            run_id,
            _now(),
            category,
            dumps(keywords),
            tone,
            brand_brief,
            max_length,
            dumps(extensions),
            generate_count,
            dumps(settings),
        ),
    )
    await db.commit()
    return await get_run(db, run_id)  # type: ignore[return-value]


async def get_run(db: aiosqlite.Connection, run_id: str) -> dict[str, Any] | None:
    cur = await db.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
    row = await cur.fetchone()
    data = row_to_dict(row)
    if not data:
        return None
    data["keywords"] = loads(data["keywords"], [])
    data["extensions"] = loads(data["extensions"], [])
    data["settings"] = loads(data["settings_json"], {})
    data["progress"] = loads(data["progress_json"], {})
    return data


async def list_runs(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    cur = await db.execute("SELECT * FROM runs ORDER BY created_at DESC")
    rows = await cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        data["keywords"] = loads(data["keywords"], [])
        data["extensions"] = loads(data["extensions"], [])
        data["settings"] = loads(data["settings_json"], {})
        data["progress"] = loads(data["progress_json"], {})
        out.append(data)
    return out


async def update_run_status(
    db: aiosqlite.Connection,
    run_id: str,
    status: str,
    progress: dict[str, Any] | None = None,
) -> None:
    if progress is None:
        await db.execute("UPDATE runs SET status = ? WHERE id = ?", (status, run_id))
    else:
        await db.execute(
            "UPDATE runs SET status = ?, progress_json = ? WHERE id = ?",
            (status, dumps(progress), run_id),
        )
    await db.commit()


async def update_run_settings(
    db: aiosqlite.Connection,
    run_id: str,
    settings: dict[str, Any],
) -> None:
    await db.execute(
        "UPDATE runs SET settings_json = ? WHERE id = ?",
        (dumps(settings), run_id),
    )
    await db.commit()


async def upsert_candidates(
    db: aiosqlite.Connection,
    run_id: str,
    candidates: list[dict[str, Any]],
) -> None:
    await db.executemany(
        """
        INSERT INTO candidates (
            run_id, name, pronunciation, method, total_score, scores_json,
            domains_json, conflict_level, conflict_notes, rejected, reject_reason, favorite,
            radio_score, radio_pass, radio_spellings, radio_explanation, radio_result
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, name) DO UPDATE SET
            pronunciation = excluded.pronunciation,
            method = excluded.method,
            total_score = excluded.total_score,
            scores_json = excluded.scores_json,
            domains_json = excluded.domains_json,
            conflict_level = excluded.conflict_level,
            conflict_notes = excluded.conflict_notes,
            rejected = excluded.rejected,
            reject_reason = excluded.reject_reason,
            radio_score = excluded.radio_score,
            radio_pass = excluded.radio_pass,
            radio_spellings = excluded.radio_spellings,
            radio_explanation = excluded.radio_explanation,
            radio_result = excluded.radio_result
        """,
        [
            (
                run_id,
                c["name"],
                c.get("pronunciation", ""),
                c.get("method", ""),
                float(c.get("total_score", 0)),
                dumps(c.get("scores", {})),
                dumps(c.get("domains", {})),
                c.get("conflict_level", "Not checked"),
                c.get("conflict_notes", ""),
                1 if c.get("rejected") else 0,
                c.get("reject_reason", ""),
                1 if c.get("favorite") else 0,
                c.get("radio_score"),
                (None if c.get("radio_pass") is None else (1 if c.get("radio_pass") else 0)),
                dumps(c.get("radio_spellings") or []),
                c.get("radio_explanation", ""),
                c.get("radio_result", ""),
            )
            for c in candidates
        ],
    )
    await db.commit()


async def list_candidates(
    db: aiosqlite.Connection,
    run_id: str,
    *,
    include_rejected: bool = False,
) -> list[dict[str, Any]]:
    if include_rejected:
        cur = await db.execute(
            "SELECT * FROM candidates WHERE run_id = ? ORDER BY total_score DESC, name ASC",
            (run_id,),
        )
    else:
        cur = await db.execute(
            """
            SELECT * FROM candidates
            WHERE run_id = ? AND rejected = 0
            ORDER BY total_score DESC, name ASC
            """,
            (run_id,),
        )
    rows = await cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        data["scores"] = loads(data["scores_json"], {})
        data["domains"] = loads(data["domains_json"], {})
        data["rejected"] = bool(data["rejected"])
        data["favorite"] = bool(data["favorite"])
        data["radio_spellings"] = loads(data.get("radio_spellings") or "[]", [])
        data["trademark_matches"] = loads(data.get("trademark_matches") or "[]", [])
        if data.get("radio_pass") is not None:
            data["radio_pass"] = bool(data["radio_pass"])
        out.append(data)
    return out


async def set_favorite(
    db: aiosqlite.Connection,
    run_id: str,
    name: str,
    favorite: bool,
) -> bool:
    cur = await db.execute(
        "UPDATE candidates SET favorite = ? WHERE run_id = ? AND name = ?",
        (1 if favorite else 0, run_id, name),
    )
    await db.commit()
    return cur.rowcount > 0


async def record_favorite_signal(
    db: aiosqlite.Connection,
    *,
    name_key: str,
    length: int,
    shape: str,
    method: str = "",
    naming_style: str = "",
    ends_vowel: bool = False,
    active: bool = True,
) -> None:
    """Upsert a learning signal when a user stars/unstars a name."""
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS favorite_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            name_key TEXT NOT NULL,
            length INTEGER NOT NULL,
            shape TEXT NOT NULL,
            method TEXT NOT NULL DEFAULT '',
            naming_style TEXT NOT NULL DEFAULT '',
            ends_vowel INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    now = datetime.now(timezone.utc).isoformat()
    if active:
        await db.execute(
            """
            INSERT INTO favorite_signals
            (created_at, name_key, length, shape, method, naming_style, ends_vowel, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (now, name_key, length, shape, method, naming_style, 1 if ends_vowel else 0),
        )
    else:
        await db.execute(
            "UPDATE favorite_signals SET active = 0 WHERE name_key = ? AND active = 1",
            (name_key,),
        )
    await db.commit()


async def list_favorite_signals(
    db: aiosqlite.Connection,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS favorite_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            name_key TEXT NOT NULL,
            length INTEGER NOT NULL,
            shape TEXT NOT NULL,
            method TEXT NOT NULL DEFAULT '',
            naming_style TEXT NOT NULL DEFAULT '',
            ends_vowel INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        )
        """
    )
    cur = await db.execute(
        """
        SELECT name_key, length, shape, method, naming_style, ends_vowel
        FROM favorite_signals
        WHERE active = 1
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = await cur.fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "key": r[0],
                "length": int(r[1] or 0),
                "shape": r[2] or "invented",
                "method": r[3] or "",
                "naming_style": r[4] or "",
                "ends_vowel": bool(r[5]),
            }
        )
    return out


async def update_candidate_domains(
    db: aiosqlite.Connection,
    run_id: str,
    name: str,
    domains: dict[str, Any],
    total_score: float | None = None,
    scores: dict[str, Any] | None = None,
) -> None:
    if total_score is None or scores is None:
        await db.execute(
            "UPDATE candidates SET domains_json = ? WHERE run_id = ? AND name = ?",
            (dumps(domains), run_id, name),
        )
    else:
        await db.execute(
            """
            UPDATE candidates
            SET domains_json = ?, total_score = ?, scores_json = ?
            WHERE run_id = ? AND name = ?
            """,
            (dumps(domains), total_score, dumps(scores), run_id, name),
        )
    await db.commit()


async def update_candidate_conflict(
    db: aiosqlite.Connection,
    run_id: str,
    name: str,
    level: str,
    notes: str,
    total_score: float | None = None,
    scores: dict[str, Any] | None = None,
) -> None:
    if total_score is None or scores is None:
        await db.execute(
            """
            UPDATE candidates
            SET conflict_level = ?, conflict_notes = ?
            WHERE run_id = ? AND name = ?
            """,
            (level, notes, run_id, name),
        )
    else:
        await db.execute(
            """
            UPDATE candidates
            SET conflict_level = ?, conflict_notes = ?, total_score = ?, scores_json = ?
            WHERE run_id = ? AND name = ?
            """,
            (level, notes, total_score, dumps(scores), run_id, name),
        )
    await db.commit()


async def update_candidate_trademark(
    db: aiosqlite.Connection,
    run_id: str,
    name: str,
    *,
    risk: str,
    summary: str,
    reason: str,
    matches: list[dict[str, Any]],
) -> None:
    await db.execute(
        """
        UPDATE candidates
        SET trademark_risk = ?, trademark_summary = ?, trademark_reason = ?, trademark_matches = ?
        WHERE run_id = ? AND name = ?
        """,
        (risk, summary, reason, dumps(matches), run_id, name),
    )
    await db.commit()


async def get_domain_cache(
    db: aiosqlite.Connection,
    domain: str,
    max_age_hours: int,
) -> dict[str, Any] | None:
    cur = await db.execute("SELECT * FROM domain_cache WHERE domain = ?", (domain.lower(),))
    row = await cur.fetchone()
    if not row:
        return None
    data = dict(row)
    checked = datetime.fromisoformat(data["checked_at"])
    age = datetime.now(timezone.utc) - checked
    if age.total_seconds() > max_age_hours * 3600:
        return None
    return {
        "domain": data["domain"],
        "status": data["status"],
        "detail": data["detail"],
        "premium": bool(data["premium"]),
        "checked_at": data["checked_at"],
        "raw": loads(data["raw_json"], {}),
        "cached": True,
    }


async def set_domain_cache(
    db: aiosqlite.Connection,
    *,
    domain: str,
    status: str,
    detail: str = "",
    premium: bool = False,
    raw: dict[str, Any] | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO domain_cache (domain, status, detail, premium, checked_at, raw_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(domain) DO UPDATE SET
            status = excluded.status,
            detail = excluded.detail,
            premium = excluded.premium,
            checked_at = excluded.checked_at,
            raw_json = excluded.raw_json
        """,
        (
            domain.lower(),
            status,
            detail,
            1 if premium else 0,
            _now(),
            dumps(raw or {}),
        ),
    )
    await db.commit()
