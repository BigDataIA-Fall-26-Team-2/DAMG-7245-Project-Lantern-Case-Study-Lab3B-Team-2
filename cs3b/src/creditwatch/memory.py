"""Governed memory: writes by origin, one store per mandate."""
import difflib
import json
import re
import sqlite3
from pathlib import Path


def propose_write(scope, content, origin, message_id, audit,
                  principal_md, proposals_dir, today):
    """origin comes from the channel's authentication,
    never from the model's claim about where text came from."""
    if origin == "principal" and message_id:
        with open(principal_md, "a", encoding="utf-8") as f:
            f.write(f"- {content} ({message_id}, {today})\n")
        audit.record("memory_write", file="PRINCIPAL.md",
                     message_id=message_id, scope=scope)
        return "written"
    d = Path(proposals_dir)
    d.mkdir(parents=True, exist_ok=True)
    pid = f"prop-{len(list(d.glob('*.json'))) + 1:04d}"
    (d / f"{pid}.json").write_text(json.dumps(
        {"content": content, "origin": origin, "scope": scope}))
    audit.record("proposal", proposal_id=pid, origin=origin,
                 scope=scope)
    return "proposed"


class MandateStore:
    """One SQLite file per mandate: isolation is physical."""

    def __init__(self, root, mandate):
        d = Path(root) / mandate
        d.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(d / "memory.sqlite")
        self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS mem "
                        "USING fts5(text, source)")

    def add(self, text, source):
        self.db.execute("INSERT INTO mem VALUES (?, ?)",
                        (text, source))
        self.db.commit()

    def search(self, query, k=5):
        terms = re.findall(r"[0-9A-Za-z]+", query)
        if not terms:
            return []
        q = " OR ".join(f'"{t}"' for t in terms)
        return self.db.execute(
            "SELECT text, source FROM mem WHERE mem MATCH ? "
            "ORDER BY rank LIMIT ?", (q, k)).fetchall()


def append_log(root, mandate, day, text):
    """Append-only daily log; returns the line's reference."""
    d = Path(root) / mandate / "log"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{day}.md"
    n = len(f.read_text().splitlines()) if f.exists() else 0
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(f"{n + 1}. {text}\n")
    return f"log/{day}.md#{n + 1}"


def compact(root, mandate, before_day):
    """Older log lines into MEMORY.md, each linked to its
    source line; returns the diff for review."""
    d = Path(root) / mandate
    lines = []
    for f in sorted((d / "log").glob("*.md")):
        if f.stem >= before_day:
            continue
        for ln in f.read_text().splitlines():
            n, _, text = ln.partition(". ")
            lines.append(f"- {text[:100]} [log/{f.name}#{n}]")
    mem = d / "MEMORY.md"
    old = mem.read_text().splitlines() if mem.exists() else []
    new = ["# Memory", *lines]
    mem.write_text("\n".join(new) + "\n")
    return list(difflib.unified_diff(old, new, "MEMORY.md (before)",
                                     "MEMORY.md (after)", lineterm=""))
