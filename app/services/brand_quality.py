"""Brand credibility gates.

Goal: keep names that feel intentional — like a company that could raise —
and reject pronounceable gibberish assembled from random syllables.
"""

from __future__ import annotations

import re
from functools import lru_cache

from app.config import load_yaml
from app.services.filter import compact_key
from app.services.pronunciation import consecutive_consonants, syllable_count
from app.services.real_words import is_real_word_candidate, real_word_set
from app.services.soft_invented import is_soft_invented

# Mid-name vowel collisions that produce Bapaen / Breduora-class junk.
AWKWARD_VOWEL_JUNCTIONS = frozenset({"ae", "ao", "eu", "iu", "uo", "ua", "aa", "ii", "uu"})

# Consonant pairs almost never seen in credible English brand names.
AWKWARD_CONSONANT_PAIRS = frozenset(
    {
        "bf",
        "bg",
        "bk",
        "bp",
        "bv",
        "bx",
        "bz",
        "cj",
        "cp",
        "cv",
        "cx",
        "cz",
        "db",
        "df",
        "dk",
        "dp",
        "dq",
        "dv",
        "dx",
        "dz",
        "fb",
        "fc",
        "fd",
        "fg",
        "fh",
        "fk",
        "fm",
        "fn",
        "fp",
        "fq",
        "fv",
        "fw",
        "fx",
        "fz",
        "gb",
        "gc",
        "gd",
        "gf",
        "gj",
        "gk",
        "gp",
        "gq",
        "gv",
        "gx",
        "gz",
        "hb",
        "hc",
        "hd",
        "hf",
        "hg",
        "hj",
        "hk",
        "hp",
        "hq",
        "hv",
        "hx",
        "hz",
        "jb",
        "jc",
        "jd",
        "jf",
        "jg",
        "jh",
        "jk",
        "jl",
        "jm",
        "jn",
        "jp",
        "jq",
        "jr",
        "js",
        "jt",
        "jv",
        "jw",
        "jx",
        "jz",
        "kb",
        "kc",
        "kd",
        "kf",
        "kg",
        "kj",
        "kp",
        "kq",
        "kv",
        "kx",
        "kz",
        "mj",
        "mq",
        "mv",
        "mx",
        "mz",
        "pb",
        "pc",
        "pd",
        "pf",
        "pg",
        "pj",
        "pk",
        "pm",
        "pn",
        "pq",
        "pv",
        "pw",
        "px",
        "pz",
        "sb",
        "sd",
        "sf",
        "sg",
        "sj",
        "sr",
        "sv",
        "sx",
        "sz",
        "tb",
        "tc",
        "td",
        "tf",
        "tg",
        "tj",
        "tk",
        "tm",
        "tn",
        "tp",
        "tq",
        "tv",
        "tx",
        "tz",
        "vb",
        "vc",
        "vd",
        "vf",
        "vg",
        "vh",
        "vj",
        "vk",
        "vm",
        "vn",
        "vp",
        "vq",
        "vr",
        "vs",
        "vt",
        "vw",
        "vx",
        "vz",
        "wb",
        "wc",
        "wd",
        "wf",
        "wg",
        "wj",
        "wk",
        "wl",
        "wm",
        "wp",
        "wq",
        "wv",
        "wx",
        "wz",
        "xb",
        "xc",
        "xd",
        "xf",
        "xg",
        "xh",
        "xj",
        "xk",
        "xl",
        "xm",
        "xn",
        "xp",
        "xq",
        "xr",
        "xs",
        "xv",
        "xw",
        "xz",
        "zb",
        "zc",
        "zd",
        "zf",
        "zg",
        "zj",
        "zk",
        "zl",
        "zm",
        "zn",
        "zp",
        "zq",
        "zr",
        "zs",
        "zt",
        "zv",
        "zw",
        "zx",
        "zz",
    }
)

GIBBERISH_SIGNATURES = (
    "flar",
    "oofl",
    "athu",
    "duora",
    "apaen",
    "eduor",
    "bruora",
    "bapae",
    "bredu",
    "brath",
    "boof",
)

PRODUCT_ENDINGS = (
    "nest",
    "place",
    "home",
    "room",
    "proof",
    "look",
    "live",
    "view",
    "fit",
    "sure",
    "wise",
    "furniture",
    "furni",
    "deco",
)

# Endings that appear on real successful brands — not AI suffix soup (va/ly/cel/hub).
CREDIBLE_ENDINGS = (
    "a",
    "o",
    "y",
    "el",
    "en",
    "on",
    "an",
    "ar",
    "er",
    "or",
    "us",
    "um",
    "ix",
    "is",
    "ia",
    "io",
    "ra",
    "ro",
    "ma",
    "na",
    "ta",
    "form",
    "line",
    "path",
    "way",
    "base",
    "rise",
)


@lru_cache
def _lexicon() -> dict:
    return load_yaml("brand_lexicon.yaml")


@lru_cache
def lexicon_words() -> frozenset[str]:
    data = _lexicon()
    words: set[str] = set()
    for key in (
        "short_punchy",
        "soft_brandables",
        "classical_roots",
        "nature_roots",
        "science_roots",
        "architecture_roots",
        "geography_roots",
        "astronomy_roots",
        "mythology_roots",
    ):
        for w in data.get(key) or []:
            s = str(w).strip().lower()
            if s:
                words.add(s)
    return frozenset(words)


def join_morphemes(left: str, right: str) -> str:
    """Join two morphemes without ugly vowel pileups."""
    a = re.sub(r"[^a-z]", "", left.lower())
    b = re.sub(r"[^a-z]", "", right.lower())
    if not a or not b:
        return a or b
    if a.endswith(b):
        return a
    if b.startswith(a) and len(b) > len(a):
        return b
    vowels = set("aeiou")
    while a and b and a[-1] in vowels and b[0] in vowels:
        if len(b) > 1:
            b = b[1:]
        else:
            a = a[:-1]
            break
    if a and b and a[-1] == b[0]:
        b = b[1:]
    return a + b


def title_name(key: str) -> str:
    return key[:1].upper() + key[1:] if key else key


def _has_awkward_pattern(key: str) -> bool:
    if any(sig in key for sig in GIBBERISH_SIGNATURES):
        return True

    # Multi-letter nucleus leftovers from old generator
    if "oo" in key and key not in lexicon_words() and not key.endswith("oon"):
        # allow "loom", "booth" via lexicon; reject "booflar"
        if re.search(r"[bcdfghjklmnpqrstvwxyz]oo[bcdfghjklmnpqrstvwxyz]{2,}", key):
            return True

    vowels = set("aeiou")
    for i in range(len(key) - 1):
        pair = key[i : i + 2]
        if pair[0] in vowels and pair[1] in vowels:
            # Allow common brand diphthongs
            if pair in {"ai", "ay", "ea", "ee", "ei", "ey", "ie", "oa", "oi", "oy", "ou"}:
                continue
            if pair in AWKWARD_VOWEL_JUNCTIONS:
                if key in lexicon_words():
                    continue
                return True
        elif pair[0] not in vowels and pair[1] not in vowels and pair[0] != "y" and pair[1] != "y":
            # Allow common English clusters
            if pair in {
                "bl",
                "br",
                "ch",
                "ck",
                "cl",
                "cr",
                "ct",
                "dr",
                "fl",
                "fr",
                "ft",
                "gl",
                "gr",
                "ld",
                "lf",
                "lk",
                "ll",
                "lm",
                "ln",
                "lp",
                "lt",
                "mb",
                "mp",
                "nc",
                "nd",
                "ng",
                "nk",
                "nn",
                "ns",
                "nt",
                "ph",
                "pl",
                "pr",
                "pt",
                "rb",
                "rc",
                "rd",
                "rf",
                "rg",
                "rk",
                "rl",
                "rm",
                "rn",
                "rp",
                "rr",
                "rs",
                "rt",
                "rv",
                "sc",
                "sh",
                "sk",
                "sl",
                "sm",
                "sn",
                "sp",
                "ss",
                "st",
                "th",
                "tr",
                "ts",
                "tt",
                "tw",
                "wh",
                "wr",
                "xt",
            }:
                continue
            if pair in AWKWARD_CONSONANT_PAIRS:
                return True
            # Unknown CC mid-word (not at start cluster): suspicious for inventeds
            if i > 0 and i < len(key) - 2 and pair not in {"st", "nd", "nt", "mp", "ng", "ck"}:
                # only reject if both are hard stops
                if pair[0] in "bcdfgkptv" and pair[1] in "bcdfgkptv":
                    return True
    return False


def _looks_like_real_brand_shape(key: str) -> bool:
    n = len(key)
    syll = syllable_count(key)
    if n < 4 or n > 10:
        return False
    if syll < 1 or syll > 3:
        return False
    if consecutive_consonants(key) > 3:
        return False
    if syll == 1:
        return 4 <= n <= 7
    if syll == 2:
        return 4 <= n <= 8
    return n <= 9


def credibility_score(name: str, *, method: str = "") -> float:
    """0–100. Rough 'would this raise $100M?' heuristic."""
    key = compact_key(name)
    if not key:
        return 0.0

    score = 52.0
    syll = syllable_count(key)
    n = len(key)

    # Soft-invented covers the banned-name list — a name the manifesto
    # explicitly rejects must not survive on shape points alone.
    if is_soft_invented(key):
        score -= 60

    # No consonants (eaiou) or no vowels (strngth): not a plausible word.
    if not re.search(r"[bcdfghjklmnpqrstvwxz]", key) or not re.search(r"[aeiouy]", key):
        score -= 45

    if key in lexicon_words() or key in real_word_set():
        score += 30
    elif is_real_word_candidate(key):
        score += 26
    else:
        for root in lexicon_words():
            if len(root) >= 4 and (root in key or key.startswith(root[: max(3, len(root) - 1)])):
                score += 12
                break

    if _clumsy_suffix_on_complete_root(key):
        score -= 40

    if _looks_like_real_brand_shape(key):
        score += 14
    else:
        score -= 22

    if _has_awkward_pattern(key):
        score -= 48

    if key.endswith(PRODUCT_ENDINGS):
        score -= 40

    if any(key.endswith(e) for e in CREDIBLE_ENDINGS):
        score += 6

    if 5 <= n <= 8:
        score += 12
    elif n in {4, 9}:
        score += 4
    else:
        score -= 10

    if syll == 2:
        score += 10
    elif syll == 1:
        score += 7
    elif syll == 3:
        score += 2

    if method in {"invented", "suggestive"} and key not in lexicon_words():
        if score < 72:
            score -= 6

    rare = sum(1 for ch in key if ch in "qjxz")
    score -= rare * 5

    # Tech-buzzword tails (HomeAI / VisionXR class) are the exact sludge this
    # tool exists to avoid — penalize unconditionally, not only when the user
    # remembered to put them in the avoid list.
    if (
        len(key) > 4
        and re.search(r"(ai|xr|vr|gpt)$", key)
        and key not in lexicon_words()
        and key not in real_word_set()
    ):
        score -= 30

    return max(0.0, min(100.0, score))


def _clumsy_suffix_on_complete_root(key: str) -> bool:
    """Reject Orionan / Phoscel / Magnama — complete roots with junk glued on."""
    words = lexicon_words()
    if key in words:
        return False
    if key.endswith(("osis", "itis", "esis")) and key not in words:
        return True
    for root in words:
        if len(root) < 4:
            continue
        if key.startswith(root) and len(key) > len(root):
            tail = key[len(root) :]
            if len(tail) <= 4 and tail in {
                "a", "o", "y", "ly", "el", "en", "on", "an", "ar", "er", "or",
                "us", "um", "ix", "is", "ia", "io", "ra", "cel", "bel", "del",
                "nel", "lin", "na", "ma", "ta", "ko", "to", "osis", "sis", "via",
            }:
                return True
    return False


def brand_quality_ok(name: str, *, method: str = "", min_score: float = 64.0) -> tuple[bool, str]:
    """Hard gate used during generation. Returns (ok, reason)."""
    key = compact_key(name)
    if not key:
        return False, "empty"

    # Soft inventeds fail the commercial bar regardless of method.
    if is_soft_invented(key):
        return False, "soft invented / AI-sounding"

    # Real-word / familiar mode: must be an intact curated dictionary word (or two joined).
    if method == "real_word":
        if not is_real_word_candidate(key):
            return False, "not a curated real word"
        # Allow slightly longer authentic words (sanctuary, threshold).
        if len(key) > 12 or consecutive_consonants(key) > 3:
            return False, "unlikely real-word shape"
        score = credibility_score(name, method=method)
        if score < max(60.0, min_score - 8):
            return False, f"low credibility ({score:.0f})"
        return True, ""

    if method in {"invented", "evocative", "suggestive", "llm"} and key.endswith(PRODUCT_ENDINGS):
        return False, "product ending on brandable"

    # Invented: must be a curated lexicon word (no random coinage).
    if method == "invented" and key not in lexicon_words():
        return False, "invented not in brand lexicon"

    # Evocative/suggestive non-lexicon names need a higher bar.
    if method in {"evocative", "suggestive"} and key not in lexicon_words():
        if _clumsy_suffix_on_complete_root(key):
            return False, "clumsy suffix on complete root"
        if len(key) < 6 and method == "evocative":
            return False, "thin evocative"
        # Reject scrap endings like …sh / …lab glued oddly
        if key.endswith(("sh", "lab", "hub")) and not any(
            key.endswith(r) for r in ("flash", "marsh") if False
        ):
            if key.endswith("sh") and not key.endswith(("ash", "ush", "ish", "esh")):
                return False, "scrap ending"
            if key.endswith(("lab", "hub")) and len(key) <= 7:
                # Allow ClearLab-length only when left half is a real word ≥4
                left = key[:-3]
                if left not in lexicon_words() and len(left) < 4:
                    return False, "weak lab/hub compound"

    if _has_awkward_pattern(key):
        return False, "awkward letter pattern"

    if _clumsy_suffix_on_complete_root(key):
        return False, "clumsy suffix on complete root"

    if not _looks_like_real_brand_shape(key):
        return False, "unlikely brand shape"

    if re.search(r"(.)\1\1", key):
        return False, "repeated letters"

    if re.search(r"[aeiou]{3,}", key):
        return False, "vowel pileup"

    # TitleCase compounds: allow Basecamp / Mailchimp length; reject DigitalOcean-class monsters.
    if method == "compound" and len(key) > 14:
        return False, "heavy compound"

    score = credibility_score(name, method=method)
    # Lexicon membership is a hint, not a free pass for mediocre shapes.
    if key in lexicon_words() and score >= 62:
        return True, ""

    if score < min_score:
        return False, f"low credibility ({score:.0f})"

    return True, ""
