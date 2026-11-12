"""Workspace files: who may write each, and context assembly."""
import shutil
from pathlib import Path

AUTHORITY = {          # file: (authority, written by)
    "SOUL.md": ("instruction", "team, in Git"),
    "AGENTS.md": ("instruction", "team, in Git"),
    "HEARTBEAT.md": ("instruction", "team, in Git"),
    "PRINCIPAL.md": ("instruction", "governed path only"),
    "mandates/*/MANDATE.md": ("data", "seed, then governed"),
    "mandates/*/WATCHLIST.md": ("data", "approved writes"),
    "mandates/*/log/*.md": ("data", "agent, append-only"),
    "mandates/*/MEMORY.md": ("data", "compaction job"),
    "proposals/": ("pending", "anything else"),
}


def ntok(s):                                # use a tokenizer
    return max(1, len(s) // 4)


def clip(text, budget):
    """Whole lines until the budget is spent."""
    out, used = [], 0
    for line in text.splitlines():
        t = ntok(line)
        if used + t > budget:
            break
        out.append(line)
        used += t
    return "\n".join(out), used


ORDER = ["soul", "principal", "agents", "mandate",
         "watchlist", "skills_index", "memory"]


def assemble(parts, budgets):
    ctx, report = [], {}
    for k in ORDER:                             # fixed order
        text = parts.get(k, "")
        body, used = clip(text, budgets[k])
        full = sum(ntok(x) for x in text.splitlines())
        report[k] = {"used": used, "budget": budgets[k],
                     "clipped": used < full}
        ctx.append(f"## {k}\n{body}")
    return "\n\n".join(ctx), report


def load_parts(ws, mandate, skills_index="", memory=None):
    """Only the ACTIVE mandate's files enter the context."""
    ws = Path(ws)
    from . import memory as memory_module
    m = memory_module.mandate_directory(ws / "mandates", mandate)
    if memory is None:
        memory = memory_module.context_memory(ws / "mandates", mandate)

    def read(p):
        memory_module.confined_file(m if p.parent == m else ws, p)
        return p.read_text() if p.exists() else ""
    return {"soul": read(ws / "SOUL.md"),
            "principal": read(ws / "PRINCIPAL.md"),
            "agents": read(ws / "AGENTS.md"),
            "mandate": read(m / "MANDATE.md"),
            "watchlist": read(m / "WATCHLIST.md"),
            "skills_index": skills_index, "memory": memory}


def fresh_workspace(seed, dest):
    """Copy the seed workspace; NAME.seed.md becomes NAME.md."""
    dest = Path(dest)
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(seed, dest)
    for f in dest.rglob("*.seed.md"):
        f.rename(f.with_name(f.name.replace(".seed.md", ".md")))
    return dest
