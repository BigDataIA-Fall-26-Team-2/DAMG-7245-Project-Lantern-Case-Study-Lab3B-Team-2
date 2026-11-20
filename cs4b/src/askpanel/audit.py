"""Audit ledger v0: one event per decision. Hashes, ids and
redacted summaries only: never secrets or client content."""
import json


class Ledger:
    def __init__(self, path=None, clock=None):
        self.path, self.clock, self.events = path, clock, []

    def record(self, kind, **fields):
        e = {"event_id": f"ev-{len(self.events) + 1:05d}",
             "ts": self.clock().isoformat() if self.clock else None,
             "kind": kind, **fields}
        self.events.append(e)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(e, sort_keys=True) + "\n")
        return e

    def find(self, kind=None, **match):
        return [e for e in self.events
                if (kind is None or e["kind"] == kind)
                and all(e.get(k) == v for k, v in match.items())]
