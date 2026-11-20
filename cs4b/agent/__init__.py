"""The Ask the Panel agent (Labs 33B to 36B). Puts cs4b/ and cs4b/src on sys.path so
`agent.*`, `services.*` and `askpanel` import the same way from scripts, tests and the app."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
