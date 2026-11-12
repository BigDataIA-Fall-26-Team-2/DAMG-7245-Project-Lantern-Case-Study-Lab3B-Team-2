"""The two-period panel: your Case Study 2B holdings for admitted
filings, current schedule AND the prior fiscal year-end schedule
from the same filing, one row per holding per period."""
from pathlib import Path

import pandas as pd

REQUIRED = ["adsh", "cik", "name", "form", "period", "ddate",
            "period_role", "identifier", "investment_type",
            "fair_value", "cost", "principal", "pik_rate",
            "maturity", "source_rows"]
NUMERIC = ["fair_value", "cost", "principal", "pik_rate",
           "interest_rate", "spread", "pct_net_assets"]


def from_holdings(h, admitted):
    """Case Study 2B coalesced holdings -> the 3B panel."""
    p = h[h["adsh"].isin(set(admitted))].copy()
    p["period_role"] = p["is_current"].map(
        {True: "current", False: "prior"})
    return p


def load_panel(path):
    path = Path(path)
    if path.suffix == ".parquet":
        p = pd.read_parquet(path)
    else:
        p = pd.read_csv(path, dtype={"adsh": str, "cik": str,
                                      "source_rows": str})
    for c in NUMERIC:
        if c in p.columns:
            p[c] = pd.to_numeric(p[c], errors="coerce")
    return p


def check_mandates(mandates, p):
    """Positions must name BDCs exactly as the panel (SUB) does:
    a near miss routes nothing, silently. [] means all match."""
    import difflib
    names = sorted(set(p["name"]))
    out = []
    for mid, m in mandates.items():
        for bdc in m["positions"]:
            if bdc not in names:
                near = difflib.get_close_matches(
                    bdc.upper(), [n.upper() for n in names], 1, 0.6)
                out.append(f"{mid}: {bdc!r} is not in the panel"
                           + (f" (did you mean {near[0]!r}?)"
                              if near else ""))
    return out


def validate(p):
    """Problems with a panel; [] means it meets the contract."""
    out = [f"missing column: {c}" for c in REQUIRED
           if c not in p.columns]
    if out:
        return out
    bad = set(p["period_role"].dropna()) - {"current", "prior"}
    if bad or p["period_role"].isna().any():
        out.append(f"period_role must be current or prior: {bad}")
    dup = p.duplicated(["adsh", "period_role", "identifier"])
    if dup.any():
        out.append(f"{int(dup.sum())} duplicate holdings: coalesce first")
    one = p.groupby("adsh")["period_role"].nunique()
    if (one < 2).any():
        out.append(f"{int((one < 2).sum())} filing(s) lack a prior schedule")
    return out
