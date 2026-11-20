"""Your ten questions (Lab 36B): coverage rules and the saved-output format."""
from pathlib import Path

import yaml

MINIMUM = {"lookup": 2, "aggregation": 2, "cross_bdc": 2, "over_time": 2,
           "follow_up": 1, "decline": 1}
OUTPUT_FIELDS = ["id", "question", "category", "sql", "answer", "result",
                 "trace", "usd"]


def load(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []


def validate(qs):
    """Problems with questions.yaml; [] means the coverage rules are met."""
    out = []
    if len(qs) != 10:
        out.append(f"{len(qs)} questions; exactly 10 are required")
    ids = [q.get("id") for q in qs]
    if len(set(ids)) != len(ids) or None in ids:
        out.append("every question needs a unique id")
    for q in qs:
        if q.get("category") not in MINIMUM:
            out.append(f"{q.get('id')}: category must be one of {sorted(MINIMUM)}")
        if not str(q.get("question", "")).strip():
            out.append(f"{q.get('id')}: empty question")
    for cat, n in MINIMUM.items():
        k = sum(q.get("category") == cat for q in qs)
        if k < n:
            out.append(f"{cat}: {k} question(s), at least {n} required")
    seen = []
    for q in qs:
        if q.get("category") == "follow_up" and q.get("follows") not in seen:
            out.append(f"{q.get('id')}: follow_up needs 'follows' naming an earlier id")
        seen.append(q.get("id"))
    return out
