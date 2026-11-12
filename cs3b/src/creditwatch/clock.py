"""The injected clock: every time-dependent decision reads it."""
import os
from datetime import datetime

DEFAULT = "2026-10-15T06:00:00-04:00"      # the fixture morning


def clock(env=None) -> datetime:
    """LANTERN_CLOCK (ISO 8601 with offset), or 'live'."""
    v = (os.environ if env is None else env).get(
        "LANTERN_CLOCK", DEFAULT)
    if v == "live":
        return datetime.now().astimezone()
    return datetime.fromisoformat(v)
