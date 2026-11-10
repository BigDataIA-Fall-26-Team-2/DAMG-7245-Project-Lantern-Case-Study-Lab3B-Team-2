"""Execute every notebook's code cells in order, each notebook in a fresh process (no Jupyter needed).
Usage: python tools/run_notebooks.py     (uses the mode set in params.yaml)"""
import json, os, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
fails = 0
for nb in sorted((ROOT / "notebooks").glob("*.ipynb")):
    cells = [c for c in json.loads(nb.read_text())["cells"] if c["cell_type"] == "code"]
    src = "\n\n".join("".join(c["source"]) if isinstance(c["source"], list) else c["source"] for c in cells)
    bad = [l for l in src.splitlines() if l.lstrip().startswith(("%", "!"))]
    env = dict(os.environ, MPLBACKEND="Agg")
    r = subprocess.run([sys.executable, "-c", src], cwd=ROOT / "notebooks", capture_output=True, text=True, env=env)
    ok = r.returncode == 0 and not bad
    fails += not ok
    print(f"  {'PASS' if ok else 'FAIL'}  {nb.name}  ({len(cells)} code cells)")
    if not ok:
        print((r.stderr or "")[-2500:], "magics:" if bad else "", bad)
print(f"{len(list((ROOT / 'notebooks').glob('*.ipynb'))) - fails}/{len(list((ROOT / 'notebooks').glob('*.ipynb')))} notebooks run end to end")
sys.exit(1 if fails else 0)
