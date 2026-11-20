"""Build the query database (data.db) from a panel and your view.

    python tools/build_db.py        # data.use_real false: the fixture; true: data.real_panel

The same command rebuilds the same database on a clean clone, so graders get
exactly what you recorded on.
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from askpanel import db  # noqa: E402

P = yaml.safe_load((ROOT / "params.yaml").read_text())
key = "real_panel" if P["data"].get("use_real") else "panel"
panel_path = ROOT / P["data"][key]
if not panel_path.exists():
    sys.exit(f"{panel_path} not found: copy your Lab 3B panel there, or set data.use_real: false")
out = ROOT / P["data"]["db"]
vf = ROOT / P["data"]["view_sql"]
view = vf.read_text() if vf.exists() else None
p = db.load_panel(panel_path)
db.build_db(p, out, view)
print(f"{len(p)} panel rows from {p['adsh'].nunique()} filings ({key}: {P['data'][key]}) -> {out}")
if view is None:
    print("  no sql/holdings_v.sql yet: tables only (Lab 32B writes the view)")
else:
    probs = db.check_view(out, p)
    print("  holdings_v:", "meets the contract" if not probs else "; ".join(probs))
    sys.exit(1 if probs else 0)
