from __future__ import annotations

from app.services.similarity import (
    jaro_winkler,
    levenshtein,
    normalize,
    phonetic_key,
    soundex,
)
from app.services.trademark_screen import (
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    MarkRecord,
    infer_classes,
    load_marks,
    screen_name,
)


def _rec(mark: str, status: str = "live", classes: tuple[int, ...] = (20,)) -> MarkRecord:
    return MarkRecord(
        mark=mark,
        norm=normalize(mark),
        status=status,
        classes=classes,
        owner="Test Co",
        sdx=soundex(mark),
        pkey=phonetic_key(mark),
    )


def test_levenshtein():
    assert levenshtein("livora", "livora") == 0
    assert levenshtein("livora", "livorah") == 1
    assert levenshtein("livora", "livoura") == 1
    assert levenshtein("abc", "xyz") == 3


def test_jaro_winkler_prefix_boost():
    assert jaro_winkler("livora", "livorah") > 0.95
    assert jaro_winkler("livora", "zzzzzz") < 0.5


def test_soundex_phonetic():
    # The canonical example from the feature request
    assert soundex("Homio") == soundex("Homeo")
    assert soundex("Robert") == soundex("Rupert")
    assert soundex("Homio") != soundex("Nike")


def test_phonetic_key_collapses_soundalikes():
    assert phonetic_key("Fone") == phonetic_key("Phone")
    assert phonetic_key("Homio") == phonetic_key("Homeo")


def test_exact_live_mark_is_high_risk():
    marks = (_rec("Roomly", "live", (20,)),)
    result = screen_name("Roomly", category="furniture", keywords=["furniture"], marks=marks)
    assert result.risk == RISK_HIGH
    assert "Exact live trademark" in result.reason
    assert result.matches[0].kind == "exact"


def test_similar_spelling_same_class_is_medium():
    marks = (_rec("Livorah", "live", (20,)),)
    result = screen_name("Livora", category="furniture shop", keywords=["furniture"], marks=marks)
    assert result.risk == RISK_MEDIUM
    assert "same industry" in result.reason


def test_phonetic_match_same_class_is_medium():
    marks = (_rec("Homeo", "live", (20,)),)
    result = screen_name("Homio", category="furniture", keywords=["furniture"], marks=marks)
    assert result.risk == RISK_MEDIUM
    assert result.matches[0].kind in ("spelling", "phonetic")


def test_similar_mark_unrelated_class_is_low():
    marks = (_rec("Livorah", "live", (32,)),)  # beverages, unrelated to software
    result = screen_name("Livora", category="software", keywords=["software"], marks=marks)
    assert result.risk == RISK_LOW
    assert "unrelated" in result.reason


def test_dead_mark_only_is_low():
    marks = (_rec("Livora", "dead", (20,)),)
    result = screen_name("Livora", category="furniture", keywords=["furniture"], marks=marks)
    assert result.risk == RISK_LOW
    assert "dead" in result.reason.lower()


def test_no_match_is_low():
    marks = (_rec("Zzyzx", "live", (20,)),)
    result = screen_name("Brightleaf", category="furniture", keywords=["furniture"], marks=marks)
    assert result.risk == RISK_LOW
    assert result.reason == "No similar live marks found."


def test_unknown_industry_is_conservative():
    # If we can't infer the user's classes, similar live marks count as same-industry.
    marks = (_rec("Livorah", "live", (32,)),)
    result = screen_name("Livora", category="", keywords=[], marks=marks)
    assert result.risk == RISK_MEDIUM


def test_infer_classes_from_brief():
    classes = infer_classes("furniture ecommerce", ["home", "software"])
    assert 20 in classes  # furniture
    assert 35 in classes  # ecommerce
    assert 9 in classes and 42 in classes  # software


def test_bundled_dataset_flags_famous_marks():
    marks = load_marks()
    assert len(marks) > 100
    result = screen_name("Notion", category="software", keywords=["software"], marks=marks)
    assert result.risk == RISK_HIGH
    result = screen_name("Wayfair", category="furniture marketplace", keywords=["furniture"], marks=marks)
    assert result.risk == RISK_HIGH
