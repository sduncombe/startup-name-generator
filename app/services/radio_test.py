from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.filter import compact_key
from app.services.pronunciation import consecutive_consonants, pronounce_guide, syllable_count

VOWELS = set("aeiouy")

# Common hear→spell confusions
CONFUSIONS = [
    ("ph", "f"),
    ("f", "ph"),
    ("c", "k"),
    ("k", "c"),
    ("s", "c"),
    ("y", "i"),
    ("i", "y"),
    ("ee", "ea"),
    ("ea", "ee"),
    ("ie", "y"),
    ("ly", "ley"),
    ("ley", "ly"),
    ("lyn", "lin"),
    ("lin", "lyn"),
    ("ora", "ara"),
    ("ivo", "evo"),
    ("ou", "ow"),
    ("ow", "ou"),
]


@dataclass
class RadioTestResult:
    pronunciation: str
    alternate_spellings: list[str] = field(default_factory=list)
    score: float = 0.0
    passed: bool = False
    explanation: str = ""

    def to_dict(self) -> dict:
        return {
            "pronunciation": self.pronunciation,
            "alternate_spellings": self.alternate_spellings,
            "radio_score": round(self.score, 1),
            "radio_pass": self.passed,
            "radio_result": "pass" if self.passed else "fail",
            "radio_explanation": self.explanation,
        }


def radio_test(name: str, *, pass_threshold: float = 70.0) -> RadioTestResult:
    """
    Simulate a radio test: hear the name once, try to spell it.
    Higher score = more likely a listener spells the intended brand correctly.
    """
    display = name.strip()
    key = compact_key(display)
    pronunciation = pronounce_guide(display)
    if not key:
        return RadioTestResult(
            pronunciation="",
            score=0,
            passed=False,
            explanation="Empty name",
        )

    score = 92.0
    reasons: list[str] = []
    alternates: list[str] = []

    length = len(key)
    syll = syllable_count(key)

    if length <= 6:
        score += 4
    elif length <= 8:
        score += 0
    elif length <= 10:
        score -= 8
        reasons.append("longer names are harder to spell from memory")
    else:
        score -= 18
        reasons.append("too long to spell reliably after one hearing")

    if syll == 2:
        score += 4
    elif syll == 3:
        score += 0
    elif syll == 1:
        score -= 4
        reasons.append("monosyllables can collide with many spellings")
    else:
        score -= 20
        reasons.append("more than three syllables hurts recall")

    cons = consecutive_consonants(key)
    if cons >= 3:
        score -= 22
        reasons.append("consonant clusters invite misspellings")
    elif cons == 2:
        score -= 4

    # Ambiguous letter patterns
    ambiguous_hits = []
    for pattern, label in [
        (r"ph", "ph/f"),
        (r"(?<![aeiou])y(?![aeiou])", "y/i"),
        (r"qu", "qu"),
        (r"x", "x"),
        (r"eau|ieux|ough|augh", "unpredictable vowel cluster"),
        (r"[aeiou]{3,}", "long vowel run"),
        (r"(.)\1\1", "triple letter"),
    ]:
        if re.search(pattern, key):
            ambiguous_hits.append(label)
    if ambiguous_hits:
        score -= 8 * len(set(ambiguous_hits))
        reasons.append("ambiguous spelling cues: " + ", ".join(sorted(set(ambiguous_hits))))

    # Silent / unpredictable endings
    if key.endswith(("e", "ue", "es")) and syll >= 2:
        score -= 6
        reasons.append("trailing silent/soft ending is easy to drop")

    # Generate likely alternate spellings a listener might type
    alternates = _alternate_spellings(display, key)

    # Penalty grows with number of plausible wrong spellings
    if len(alternates) >= 4:
        score -= 12
        reasons.append("many plausible alternate spellings")
    elif len(alternates) >= 2:
        score -= 6
        reasons.append("a few plausible alternate spellings")
    else:
        reasons.append("few competing spellings")

    # Clear CV rhythm bonus
    if re.fullmatch(r"(?:[bcdfghjklmnpqrstvwxz]+[aeiouy]+){2,3}[bcdfghjklmnpqrstvwxz]?", key):
        score += 5

    score = max(0.0, min(100.0, score))
    passed = score >= pass_threshold
    if passed and not any("few competing" in r for r in reasons):
        explanation = "Likely spelled correctly after one hearing. " + (
            reasons[0] if reasons else "Clear sound-to-letter mapping."
        )
    elif passed:
        explanation = "Likely spelled correctly after one hearing: clear rhythm and limited alternatives."
    else:
        explanation = "Risky on radio: " + (reasons[0] if reasons else "spelling is ambiguous.")

    return RadioTestResult(
        pronunciation=pronunciation,
        alternate_spellings=alternates[:6],
        score=score,
        passed=passed,
        explanation=explanation,
    )


def _alternate_spellings(display: str, key: str) -> list[str]:
    variants: set[str] = set()
    for a, b in CONFUSIONS:
        if a in key:
            variants.add(key.replace(a, b, 1))
        if b in key:
            variants.add(key.replace(b, a, 1))

    # Drop/add common brand endings
    for src, dst in [("lyn", "lin"), ("lin", "lyn"), ("ley", "ly"), ("ly", "ley"), ("ora", "ara"), ("ara", "ora")]:
        if key.endswith(src):
            variants.add(key[: -len(src)] + dst)

    # Double letter slips
    for i, ch in enumerate(key):
        if ch in VOWELS:
            continue
        variants.add(key[:i] + ch + key[i:])  # accidental double
        if i + 1 < len(key) and key[i] == key[i + 1]:
            variants.add(key[:i] + key[i + 1 :])  # drop double

    out: list[str] = []
    for v in variants:
        if not v or v == key or len(v) < 4 or len(v) > 14:
            continue
        # Present like the original casing style
        pretty = v[:1].upper() + v[1:]
        if pretty.lower() == display.lower():
            continue
        out.append(pretty)
    # Stable unique order
    seen: set[str] = set()
    ordered: list[str] = []
    for item in out:
        k = item.lower()
        if k in seen:
            continue
        seen.add(k)
        ordered.append(item)
    return ordered
