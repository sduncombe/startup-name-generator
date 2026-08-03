#!/usr/bin/env python3
"""
Convert official USPTO bulk trademark data into the screening dataset format.

Input: one or more "Trademark applications daily/annual" XML files from the
USPTO bulk data portal (https://data.uspto.gov/, e.g. apc*.zip). Zips are
read directly; bare .xml files also work. No scraping, no network access.

Output: a JSON (or YAML) dataset consumed by the screening engine:

    {"meta": {...}, "marks": [{"mark", "status", "classes", "owner"}, ...]}

Usage:

    python tools/import_uspto.py apc*.zip -o data/uspto-trademarks.json
    TRADEMARK_DATA_PATH=data/uspto-trademarks.json uvicorn app.main:app

By default dead marks are skipped (they only add noise to screening); pass
--include-dead to keep them. Use --classes to restrict to specific Nice
classes and shrink the output.

Status mapping (approximate, from the USPTO Trademark Status Code table):
codes 600-618 are abandoned (dead) except 616 (revived); 626, 709-719 and
900+ are cancelled/expired (dead); 624, 700-708 and 800 are registered
(live); everything else with a wordmark is treated as a pending application.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from datetime import date
from pathlib import Path
from typing import IO, Any, Iterable, Iterator
from xml.etree import ElementTree as ET

STATUS_PRIORITY = {"live": 2, "pending": 1, "dead": 0}


def status_bucket(code: int) -> str:
    if code in (624, 800) or 700 <= code <= 708:
        return "live"
    if code == 616:
        return "pending"
    if 600 <= code <= 618 or code == 626 or 709 <= code <= 719 or code >= 900:
        return "dead"
    return "pending"


def _text(elem: ET.Element | None) -> str:
    return (elem.text or "").strip() if elem is not None else ""


def parse_case_files(stream: IO[bytes]) -> Iterator[dict[str, Any]]:
    """Stream <case-file> records out of one USPTO bulk XML file."""
    for _event, elem in ET.iterparse(stream, events=("end",)):
        if elem.tag != "case-file":
            continue
        header = elem.find("case-file-header")
        mark = _text(header.find("mark-identification")) if header is not None else ""
        code_text = _text(header.find("status-code")) if header is not None else ""
        classes: set[int] = set()
        for code in elem.iterfind("classifications/classification/international-code"):
            value = _text(code)
            if value.isdigit() and 1 <= int(value) <= 45:
                classes.add(int(value))
        owner = _text(elem.find("case-file-owners/case-file-owner/party-name"))
        elem.clear()

        if not mark or not code_text.isdigit():
            continue
        yield {
            "mark": mark,
            "status": status_bucket(int(code_text)),
            "classes": sorted(classes),
            "owner": owner,
        }


def iter_input_records(paths: Iterable[Path]) -> Iterator[dict[str, Any]]:
    for path in paths:
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    if not name.lower().endswith(".xml"):
                        continue
                    with zf.open(name) as f:
                        yield from parse_case_files(f)
        else:
            with path.open("rb") as f:
                yield from parse_case_files(f)


def build_dataset(
    paths: list[Path],
    *,
    include_dead: bool = False,
    only_classes: set[int] | None = None,
    max_mark_length: int = 60,
) -> dict[str, Any]:
    """Dedupe by normalized mark, keeping the most-alive status and merging classes."""
    marks: dict[str, dict[str, Any]] = {}
    scanned = 0
    for rec in iter_input_records(paths):
        scanned += 1
        if not include_dead and rec["status"] == "dead":
            continue
        if only_classes and not (set(rec["classes"]) & only_classes):
            continue
        if len(rec["mark"]) > max_mark_length:
            continue
        key = "".join(ch for ch in rec["mark"].lower() if ch.isalnum())
        if not key:
            continue
        existing = marks.get(key)
        if existing is None:
            marks[key] = rec
            continue
        existing["classes"] = sorted(set(existing["classes"]) | set(rec["classes"]))
        if STATUS_PRIORITY[rec["status"]] > STATUS_PRIORITY[existing["status"]]:
            existing["status"] = rec["status"]
            existing["mark"] = rec["mark"]
            if rec["owner"]:
                existing["owner"] = rec["owner"]

    records = sorted(marks.values(), key=lambda r: r["mark"].lower())
    return {
        "meta": {
            "name": "USPTO bulk data import",
            "sample": False,
            "source": f"Official USPTO bulk trademark data ({', '.join(p.name for p in paths)})",
            "generated": date.today().isoformat(),
            "case_files_scanned": scanned,
        },
        "marks": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert USPTO bulk trademark XML into the screening dataset format.",
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="USPTO bulk .zip or .xml files")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("data/uspto-trademarks.json"),
        help="Output dataset path (.json or .yaml, default: data/uspto-trademarks.json)",
    )
    parser.add_argument("--include-dead", action="store_true", help="Keep dead/abandoned marks")
    parser.add_argument(
        "--classes", default="",
        help="Comma-separated Nice classes to keep (e.g. 9,42); default keeps all",
    )
    args = parser.parse_args(argv)

    for path in args.inputs:
        if not path.exists():
            parser.error(f"Input not found: {path}")
    only_classes = {int(c) for c in args.classes.split(",") if c.strip()} or None

    dataset = build_dataset(
        args.inputs,
        include_dead=args.include_dead,
        only_classes=only_classes,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.suffix.lower() in (".yaml", ".yml"):
        import yaml

        with args.output.open("w", encoding="utf-8") as f:
            yaml.safe_dump(dataset, f, allow_unicode=True, sort_keys=False)
    else:
        with args.output.open("w", encoding="utf-8") as f:
            json.dump(dataset, f, ensure_ascii=False, separators=(",", ":"))

    meta = dataset["meta"]
    print(f"Scanned {meta['case_files_scanned']} case files")
    print(f"Wrote {len(dataset['marks'])} marks to {args.output}")
    print(f"Run with: TRADEMARK_DATA_PATH={args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
