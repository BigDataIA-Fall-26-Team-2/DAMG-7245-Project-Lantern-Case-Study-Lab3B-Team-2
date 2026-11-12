"""Run the tests without pytest: python tests/run_tests.py"""
import sys, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import test_creditwatch as t
fails = 0
for name in sorted(n for n in dir(t) if n.startswith("test_")):
    try:
        getattr(t, name)(); print(f"  PASS  {name}")
    except Exception:
        fails += 1; print(f"  FAIL  {name}"); traceback.print_exc()
print(f"{sum(1 for n in dir(t) if n.startswith('test_')) - fails}/{sum(1 for n in dir(t) if n.startswith('test_'))} tests pass")
sys.exit(1 if fails else 0)
