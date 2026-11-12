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


# The production-facing lab path reads durable Markdown logs directly. The
# notebook's SQLite store remains a separate demonstration/search index.
def mandate_directory(root, mandate):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", mandate):
        raise PermissionError("Invalid mandate directory")
    root = Path(root).resolve()
    directory = root / mandate
    if directory.is_symlink() or not directory.resolve().is_relative_to(root):
        raise PermissionError("Mandate directory escapes its root")
    return directory


def confined_file(directory, path):
    if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
        raise PermissionError("Memory path escapes the active mandate")
    return path


def read_entries(root, mandate, query="", limit=None):
    """Read only one mandate; keep full logs searchable after compaction."""
    from .policy import words
    directory = mandate_directory(root, mandate)
    terms = words(query).split()
    paths = [directory / "MEMORY.md", *sorted((directory / "log").glob("*.md"))]
    hits = []
    for path in paths:
        confined_file(directory, path)
        if not path.exists():
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip() and not line.startswith("#") and (not terms or any(t in words(line).split() for t in terms)):
                hits.append({"text": line, "source": f"{path.relative_to(directory)}#{n}"})
    return hits if limit is None else hits[:limit]


def context_memory(root, mandate):
    return "\n".join(f"{hit['text']} [{hit['source']}]" for hit in read_entries(root, mandate))


def preview_compaction(root, mandate, before_day):
    """Pure preview. Preserve complete facts and provenance, never delete logs."""
    import hashlib
    from datetime import date
    date.fromisoformat(before_day)
    directory = mandate_directory(root, mandate)
    target = confined_file(directory, directory / "MEMORY.md")
    old = target.read_text(encoding="utf-8") if target.exists() else ""
    # Preserve existing curated memory, adding each source at most once.
    lines = old.splitlines() if old else ["# Memory"]
    sources = {}
    for path in sorted((directory / "log").glob("*.md")):
        confined_file(directory, path)
        date.fromisoformat(path.stem)
        if path.stem >= before_day:
            continue
        content = path.read_text(encoding="utf-8")
        sources[path.name] = content
        for n, line in enumerate(content.splitlines(), 1):
            _, sep, body = line.partition(". ")
            ref = f"[log/{path.name}#{n}]"
            if line.strip() and not any(ref in existing for existing in lines):
                lines.append(f"- {body if sep else line} {ref}")
    new = "\n".join(lines) + "\n"
    payload = json.dumps([mandate, before_day, old, sources, new], sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    diff = "\n".join(difflib.unified_diff(old.splitlines(), new.splitlines(),
                        "MEMORY.md (before)", "MEMORY.md (after)", lineterm=""))
    return {"scope": mandate, "before_day": before_day, "text": new,
            "diff": diff, "review_hash": digest}


def apply_compaction(root, mandate, before_day, review_hash, validate=lambda value: None):
    """Rebuild preview and reject stale reviews before writing."""
    import hmac
    from uuid import uuid4
    plan = preview_compaction(root, mandate, before_day)
    if not hmac.compare_digest(plan["review_hash"], review_hash):
        raise ValueError("Memory or logs changed; review a fresh diff")
    validate(plan)
    directory = mandate_directory(root, mandate)
    target = confined_file(directory, directory / "MEMORY.md")
    directory.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(".memory-" + uuid4().hex + ".tmp")
    try:
        temporary.write_text(plan["text"], encoding="utf-8")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return plan
