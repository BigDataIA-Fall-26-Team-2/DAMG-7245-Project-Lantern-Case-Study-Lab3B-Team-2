"""A deterministic stand-in for a model, and a minimal READ tool
set over the fixture, so the notebooks run offline at no cost.

The stand-in plays a fixed tool plan, then writes a client note
that follows four rules ONLY when their text is in its context.
That makes before-and-after measurement visible. It is a teaching
device, never a substitute for evaluating a real model."""
import json

from . import signals as sig
from .channel import require_scope

RULES = {   # rule key: phrase it looks for in its context
    "pik": "pik present at origination is not a stress signal",
    "points": "report price changes in points",
    "exposure": "lead every client note with the client",
    "accession": "cite the accession number",
}


def short(name):
    """'FIXTURE JULIETT LENDING BDC' -> 'Juliett Lending BDC'."""
    return " ".join(w if w == "BDC" else w.title()
                    for w in name.replace("FIXTURE ", "").split())


class FixtureModel:
    def __init__(self, plan, writer=None, usd=0.00128,   # 2,000 in, 300 out at $0.40, $1.60 per M
                 tokens=(2000, 300)):
        self.plan, self.writer = plan, writer
        self.usd, self.tokens = usd, tokens

    def __call__(self, msgs):
        base = {"usd": self.usd, "tokens_in": self.tokens[0],
                "tokens_out": self.tokens[1]}
        done = sum(m["role"] == "tool" for m in msgs)
        if done < len(self.plan):
            return {**base, **self.plan[done]}
        text = self.writer(msgs) if self.writer else "done"
        return {**base, "tool": None, "text": text}


def note_writer(msgs):
    """Client note from the tool observations in msgs."""
    ctx = msgs[0]["content"].lower()
    on = {k: v in ctx for k, v in RULES.items()}
    obs = {m["name"]: json.loads(m["content"])
           for m in msgs if m["role"] == "tool"}
    prof = obs.get("mandate_profile", {})
    held = prof.get("positions", {})
    signals = [s for s in obs.get("bdc_signals", [])
               if s["name"] in held]
    exposure = "Your exposure: " + ", ".join(
        f"{short(n)} ${v:,.1f}m"
        for n, v in held.items())
    lines = [exposure] if on["exposure"] else []
    for s in signals:
        who = s["identifier"].split(" | ")[1] \
            if " | " in s["identifier"] else s["identifier"]
        bdc = short(s["name"])
        if s["rule"] == "MARKDOWN":
            d = s["before"] - s["after"]
            how = (f"down {d:.1f} points ({s['before']:.1f} to "
                   f"{s['after']:.1f})") if on["points"] else \
                f"down {100 * d / s['before']:.1f}%"
            text = f"{bdc}: {who} marked {how}"
        elif s["rule"] == "PIK_UP":
            text = (f"{bdc}: {who} PIK up from {s['before']:.2f}% "
                    f"to {s['after']:.2f}%")
        else:
            text = (f"{bdc}: {who} maturity extended from "
                    f"{s['before']} to {s['after']}")
        cite = f" [{s['adsh']}]" if on["accession"] else ""
        lines.append(text + cite)
    if not on["pik"]:
        for h in obs.get("bdc_holdings", []):
            if (h.get("pik_rate") or 0) > 0 and h["name"] in held:
                lines.append(f"PIK (watch): {h['identifier']}")
    if not on["exposure"]:
        lines.append(exposure)
    return "\n".join(lines)


def read_tools(session, audit, panel, mandates, materiality):
    """Four READ tools over the fixture. Your Part 1 MCP server
    replaces this; graders check yours, not this one."""
    def done(tool, scope):
        audit.record("tool_call", tool=tool, scope=scope,
                     decision="executed")

    def bdc_signals(scope):
        require_scope(session, scope, "public", audit)
        done("bdc_signals", scope)
        return sig.find_signals(panel, materiality) \
            .to_dict("records")

    def bdc_holdings(scope, bdc=None):
        require_scope(session, scope, "public", audit)
        cur = panel[panel["period_role"] == "current"]
        if bdc:
            cur = cur[cur["name"] == bdc]
        done("bdc_holdings", scope)
        cols = ["adsh", "name", "identifier", "fair_value",
                "principal", "pik_rate", "source_rows"]
        return cur[cols].to_dict("records")

    def mandate_profile(scope):
        require_scope(session, scope, "mandate", audit)
        done("mandate_profile", scope)
        m = mandates[scope]
        return {"client": m["client"],
                "positions": m["positions"]}

    def watchlist_read(scope):
        require_scope(session, scope, "mandate", audit)
        done("watchlist_read", scope)
        return {"entries": mandates[scope].get("watchlist", [])}
    return {"bdc_signals": bdc_signals,
            "bdc_holdings": bdc_holdings,
            "mandate_profile": mandate_profile,
            "watchlist_read": watchlist_read}
