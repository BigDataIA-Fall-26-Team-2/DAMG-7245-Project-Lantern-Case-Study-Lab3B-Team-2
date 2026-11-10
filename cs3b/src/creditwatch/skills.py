"""Agent Skills: an index for the context, a lockfile for trust."""
import hashlib
import re
from pathlib import Path

import yaml

FM = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.S)   # LF or CRLF


def frontmatter(md):
    m = FM.match(md)
    if not m:
        raise ValueError("missing frontmatter")
    return yaml.safe_load(m.group(1))       # multi-line ok


def load_skills(root):
    return {p.parent.name: p.read_text()
            for p in sorted(Path(root).glob("*/SKILL.md"))}


def skill_index(skills):                  # name -> SKILL.md
    return "\n".join(
        f"- {frontmatter(t)['name']}: "
        f"{frontmatter(t)['description']}"
        for t in skills.values())


def folder_hash(d):
    """Every file in the skill: scripts run, so pin them too."""
    h = hashlib.sha256()
    for f in sorted(p for p in Path(d).rglob("*") if p.is_file()
                    and "__pycache__" not in p.parts):
        h.update(f.relative_to(d).as_posix().encode() + b"\0")
        h.update(f.read_bytes() + b"\0")
    return h.hexdigest()


def lock(root):
    return {p.parent.name: folder_hash(p.parent)
            for p in sorted(Path(root).glob("*/SKILL.md"))}


def verify(root, lockfile):
    """Refuse to start if any skill differs from its pin."""
    now = lock(root)
    bad = sorted(n for n in now.keys() | lockfile.keys()
                 if now.get(n) != lockfile.get(n))
    if bad:
        raise RuntimeError(f"skill hash mismatch: {bad}")
