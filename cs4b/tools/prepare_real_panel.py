"""Copy our Lab 3B real panel into cs4b/, clearing principal on the current rows that
have a principal but no fair value.

    python tools/prepare_real_panel.py [source]     # default: ../cs3b/data/real/panel_2p.parquet

Why: the Lab 32B view contract (askpanel.db.check_view) treats every row with
principal > 0 as debt and requires it to have price = 100 * fair_value / principal.
For these rows fair_value is missing in the SEC data, so no price can be computed
and nothing should be invented. Clearing principal on exactly these rows keeps them
in the view (fair value totals per filing are unchanged, since their fair value is
NULL) as rows with price NULL and is_debt 0. Every other row is copied unchanged.
"""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "cs3b/data/real/panel_2p.parquet"
dst = ROOT / "data/real/panel_2p.parquet"

p = pd.read_parquet(src)
mask = (p["period_role"] == "current") & p["fair_value"].isna() & (p["principal"] > 0)
print(f"{len(p)} rows read from {src}")
print(f"clearing principal on {int(mask.sum())} current row(s) with principal > 0 and no fair value")
for _, r in p[mask].head(5).iterrows():
    print(f"  {r['name']} | {r['identifier']} | principal {r['principal']:,.0f}")
p.loc[mask, "principal"] = None
dst.parent.mkdir(parents=True, exist_ok=True)
p.to_parquet(dst, index=False)
print(f"wrote {dst}")
