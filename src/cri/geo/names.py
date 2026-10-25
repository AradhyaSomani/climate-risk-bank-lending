"""District and state name normalisation and matching (shared by A's geocoding and B's
crosswalk). Matching is exact on the normalised name first, then fuzzy (difflib ratio), and
every non-exact match is returned with its method and score so it can be reviewed by hand.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

# common spelling variants seen across Indian sources (normalised form on the right)
ALIASES = {
    "andaman and nicobar islands": "andaman nicobar island",
    "andaman nicobar islands": "andaman nicobar island",
    "orissa": "odisha",
    "pondicherry": "puducherry",
    "uttaranchal": "uttarakhand",
    "nct of delhi": "delhi",
    "jammu and kashmir": "jammu kashmir",
    "dadra and nagar haveli": "dadra nagar haveli",
    "daman and diu": "daman diu",
}
DROP_WORDS = r"\b(district|dist|distt|the)\b"


def normalise(name: str | None) -> str:
    if name is None:
        return ""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(DROP_WORDS, " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = ALIASES.get(s, s)
    return s.replace(" and ", " ")


def best_match(name: str, candidates: dict[str, object], cutoff: float = 0.85):
    """Match `name` against {normalised name: id}. Returns (id, method, score) or None."""
    key = normalise(name)
    if key in candidates:
        return candidates[key], "exact", 1.0
    squashed = {k.replace(" ", ""): v for k, v in candidates.items()}
    if key.replace(" ", "") in squashed:
        return squashed[key.replace(" ", "")], "normalised", 1.0
    hits = difflib.get_close_matches(key, list(candidates), n=1, cutoff=cutoff)
    if hits:
        score = difflib.SequenceMatcher(None, key, hits[0]).ratio()
        return candidates[hits[0]], "fuzzy", round(score, 3)
    return None
