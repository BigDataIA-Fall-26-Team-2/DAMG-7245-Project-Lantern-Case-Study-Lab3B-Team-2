"""The record/replay model client: replay is free and exact."""
import hashlib
import json
from pathlib import Path


class CacheMiss(Exception):
    """Replay mode met a request it has never recorded."""


def request_key(req):
    canon = json.dumps(req, sort_keys=True,
                       separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


class ReplayClient:
    """mode 'replay': cache only. 'record': call, then store."""

    def __init__(self, cache_dir, mode="replay", call=None):
        self.dir, self.mode = Path(cache_dir), mode
        self.call = call
        self.dir.mkdir(parents=True, exist_ok=True)

    def __call__(self, req):
        f = self.dir / f"{request_key(req)}.json"
        if f.exists():
            return json.loads(f.read_text())
        if self.mode != "record":
            raise CacheMiss(f.name)
        out = self.call(req)            # your provider SDK call
        f.write_text(json.dumps(out, sort_keys=True))
        return out
