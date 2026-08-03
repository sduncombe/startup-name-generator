from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from import_uspto import build_dataset, main, status_bucket  # noqa: E402

CASE_FILE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<trademark-applications-daily>
  <application-information>
    <file-segments>
      <action-keys>
        <case-file>
          <serial-number>75000001</serial-number>
          <case-file-header>
            <mark-identification>LIVORA</mark-identification>
            <status-code>700</status-code>
          </case-file-header>
          <case-file-owners>
            <case-file-owner><party-name>Livora Corp</party-name></case-file-owner>
          </case-file-owners>
          <classifications>
            <classification><international-code>020</international-code></classification>
          </classifications>
        </case-file>
        <case-file>
          <serial-number>75000002</serial-number>
          <case-file-header>
            <mark-identification>HOMIO</mark-identification>
            <status-code>630</status-code>
          </case-file-header>
          <classifications>
            <classification><international-code>9</international-code></classification>
            <classification><international-code>42</international-code></classification>
          </classifications>
        </case-file>
        <case-file>
          <serial-number>75000003</serial-number>
          <case-file-header>
            <mark-identification>DEADMARK</mark-identification>
            <status-code>602</status-code>
          </case-file-header>
        </case-file>
        <case-file>
          <serial-number>75000004</serial-number>
          <case-file-header>
            <mark-identification>LIVORA</mark-identification>
            <status-code>602</status-code>
          </case-file-header>
          <classifications>
            <classification><international-code>035</international-code></classification>
          </classifications>
        </case-file>
      </action-keys>
    </file-segments>
  </application-information>
</trademark-applications-daily>
"""


def _make_zip(tmp_path: Path) -> Path:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("apc20260101.xml", CASE_FILE_XML)
    path = tmp_path / "apc20260101.zip"
    path.write_bytes(buf.getvalue())
    return path


def test_status_bucket_mapping():
    assert status_bucket(700) == "live"
    assert status_bucket(702) == "live"
    assert status_bucket(800) == "live"
    assert status_bucket(624) == "live"
    assert status_bucket(602) == "dead"
    assert status_bucket(604) == "dead"
    assert status_bucket(626) == "dead"
    assert status_bucket(710) == "dead"
    assert status_bucket(900) == "dead"
    assert status_bucket(616) == "pending"
    assert status_bucket(630) == "pending"
    assert status_bucket(686) == "pending"


def test_build_dataset_from_zip(tmp_path):
    zip_path = _make_zip(tmp_path)
    dataset = build_dataset([zip_path])
    assert dataset["meta"]["sample"] is False
    assert dataset["meta"]["case_files_scanned"] == 4

    by_mark = {m["mark"]: m for m in dataset["marks"]}
    # Dead records are skipped by default, including the dead LIVORA duplicate
    assert "DEADMARK" not in by_mark
    assert by_mark["LIVORA"]["status"] == "live"
    assert by_mark["LIVORA"]["classes"] == [20]
    assert by_mark["LIVORA"]["owner"] == "Livora Corp"
    assert by_mark["HOMIO"]["status"] == "pending"
    assert by_mark["HOMIO"]["classes"] == [9, 42]


def test_include_dead_and_class_filter(tmp_path):
    zip_path = _make_zip(tmp_path)
    dataset = build_dataset([zip_path], include_dead=True)
    by_mark = {m["mark"]: m for m in dataset["marks"]}
    assert "DEADMARK" in by_mark
    # Duplicate LIVORA records merge: live status wins, classes union
    assert by_mark["LIVORA"]["status"] == "live"
    assert by_mark["LIVORA"]["classes"] == [20, 35]

    dataset = build_dataset([zip_path], only_classes={9})
    assert [m["mark"] for m in dataset["marks"]] == ["HOMIO"]


def test_cli_writes_loadable_dataset(tmp_path, monkeypatch):
    zip_path = _make_zip(tmp_path)
    out = tmp_path / "uspto.json"
    assert main([str(zip_path), "-o", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["marks"]

    # The screening engine loads the imported dataset via TRADEMARK_DATA_PATH
    from app.config import get_settings
    from app.services.trademark_screen import (
        RISK_MEDIUM,
        clear_dataset_cache,
        dataset_info,
        load_marks,
        screen_name,
    )

    monkeypatch.setenv("TRADEMARK_DATA_PATH", str(out))
    get_settings.cache_clear()
    clear_dataset_cache()
    try:
        info = dataset_info()
        assert info["sample"] is False
        assert info["marks"] == len(data["marks"])
        result = screen_name(
            "Livorah", category="furniture", keywords=["furniture"], marks=load_marks()
        )
        assert result.risk == RISK_MEDIUM
    finally:
        get_settings.cache_clear()
        clear_dataset_cache()
