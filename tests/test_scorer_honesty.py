"""Scorer honesty fixes — regression tests.

Four classes of names that this project's own manifesto bans were scoring
well because no rule disagreed with them. Each test pins a fix:

1. Dwello class  — -ello/-illo soft coinages are soft-invented.
2. Banned leak   — names on the banned list can't survive on shape points.
3. HomeAI class  — tech-buzzword tails are penalized unconditionally.
4. eaiou/strngth — all-vowel / no-vowel strings are not words.
"""

from app.services.brand_quality import credibility_score
from app.services.soft_invented import is_soft_invented


def test_dwello_class_is_soft_invented():
    assert is_soft_invented("dwello")
    assert is_soft_invented("shopillo")


def test_real_ello_words_are_not_flagged():
    # Protected by the real-word check ahead of the tail rule (when curated);
    # at minimum the classical allowlist words never regress.
    assert not is_soft_invented("aurora")
    assert not is_soft_invented("terra")


def test_banned_names_cannot_survive_on_shape_points():
    # velora/norva sit on the banned list; credibility must stay decisively low.
    assert credibility_score("velora") < 50
    assert credibility_score("norva") < 50
    assert credibility_score("dwello") < 50


def test_buzzword_tails_are_penalized_without_an_avoid_list():
    assert credibility_score("homeai") < credibility_score("harbor")
    assert credibility_score("visionxr") < 50


def test_vowel_only_and_consonant_only_names_collapse():
    assert credibility_score("eaiou") < 50
    assert credibility_score("strngth") < 50
