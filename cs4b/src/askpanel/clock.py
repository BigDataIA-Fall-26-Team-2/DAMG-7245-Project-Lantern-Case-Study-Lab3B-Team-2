"""The injected clock (as in creditwatch): traces read it, so replays match."""
import os
from datetime import datetime

DEFAULT = "2026-11-16T09:00:00-05:00"      # the fixture morning


def clock(env=None) -> datetime:
    """LANTERN_CLOCK (ISO 8601 with offset), or 'live'."""
    v = (os.environ if env is None else env).get("LANTERN_CLOCK", DEFAULT)
    if v == "live":
        return datetime.now().astimezone()
    return datetime.fromisoformat(v)
