"""The query database: your two-period panel (Lab 3B) in SQLite, as two
tables, plus the holdings_v view you write in sql/holdings_v.sql.

    filings   one row per filing: adsh, cik, name, form, period, filed
    holdings  one row per holding per period: adsh, period_role, identifier, ...
"""
import sqlite3
from pathlib import Path

import pandas as pd

FILING_COLS = ["adsh", "cik", "name", "form", "period", "filed"]
FILING_REQUIRED = ["adsh", "cik", "name", "form", "period"]
HOLDING_REQUIRED = ["adsh", "period_role", "identifier", "fair_value"]
HOLDING_COLS = ["adsh", "period_role", "ddate", "identifier", "investment_type",
                "industry", "fair_value", "cost", "principal", "interest_rate",
                "spread", "pik_rate", "maturity", "pct_net_assets", "source_rows"]
NUMERIC = ["fair_value", "cost", "principal", "interest_rate", "spread",
           "pik_rate", "pct_net_assets"]

# The contract for holdings_v (Lab 32B). Write the SQL yourself.
# price: 100 * fair_value / principal where principal > 0, else NULL; if you
# round it, keep at least 2 decimals (the check allows a 0.01 difference).
# is_debt: 1 where principal > 0, else 0 (never NULL).
VIEW_COLUMNS = ["adsh", "bdc", "form", "period", "identifier", "investment_type",
                "industry", "fair_value", "cost", "principal", "price",
                "pik_rate", "interest_rate", "spread", "maturity", "is_debt"]


def load_panel(path):
    """The Lab 3B two-period panel, from CSV or Parquet."""
    path = Path(path)
    if path.suffix == ".parquet":
        p = pd.read_parquet(path)
    else:
        p = pd.read_csv(path, dtype={"adsh": str, "cik": str, "source_rows": str})
    for c in NUMERIC:
        if c in p.columns:
            p[c] = pd.to_numeric(p[c], errors="coerce")
    return p


def build_db(panel, db_path, view_sql=None):
    """Write filings and holdings to a fresh SQLite file, then run view_sql
    (your CREATE VIEW) if given. Returns the path. Optional columns your
    panel lacks (e.g. filed, industry, spread) are added as NULL, so the
    view contract always has every column to select."""
    missing = [c for c in FILING_REQUIRED + HOLDING_REQUIRED if c not in panel.columns]
    if missing:
        raise ValueError(f"panel is missing columns: {missing}")
    panel = panel.copy()
    for c in FILING_COLS + HOLDING_COLS:
        if c not in panel.columns:
            panel[c] = None
    f = panel[FILING_COLS].drop_duplicates()
    if f["adsh"].duplicated().any():
        bad = sorted(f.loc[f["adsh"].duplicated(), "adsh"])[:3]
        raise ValueError(f"filings disagree on name/form/period for adsh {bad}")
    h = panel[HOLDING_COLS]
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    con = sqlite3.connect(db_path)
    try:
        f.sort_values("adsh").to_sql("filings", con, index=False)
        h.sort_values(["adsh", "period_role", "identifier"]).to_sql(
            "holdings", con, index=False)
        con.execute("CREATE UNIQUE INDEX ix_filings_adsh ON filings(adsh)")
        con.execute("CREATE INDEX ix_holdings_adsh ON holdings(adsh, period_role)")
        if view_sql:
            con.executescript(view_sql)
        con.commit()
    finally:
        con.close()
    return db_path


def check_view(db_path, panel, tol=0.5):
    """Problems with holdings_v; [] means it meets the Lab 32B contract."""
    con = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    try:
        has = con.execute("SELECT 1 FROM sqlite_master WHERE type='view' "
                          "AND name='holdings_v'").fetchone()
        if not has:
            return ["no view named holdings_v"]
        v = pd.read_sql("SELECT * FROM holdings_v", con)
    finally:
        con.close()
    out = [f"missing column: {c}" for c in VIEW_COLUMNS if c not in v.columns]
    if out:
        return out
    cur = panel[panel["period_role"] == "current"]
    if len(v) != len(cur):
        out.append(f"row count {len(v)}, expected {len(cur)} current-period "
                   "holdings (prior rows included, or a join multiplied rows?)")
    if v["bdc"].isna().any():
        out.append(f"{int(v['bdc'].isna().sum())} rows have no bdc name (join on adsh)")
    want = cur.groupby("adsh")["fair_value"].sum()
    got = pd.to_numeric(v["fair_value"], errors="coerce").groupby(v["adsh"]).sum()
    diff = (got.reindex(want.index).fillna(0) - want).abs()
    if (diff > tol).any():
        out.append(f"fair value per filing differs for {int((diff > tol).sum())} filing(s)")
    pr = pd.to_numeric(v["principal"], errors="coerce")
    fv = pd.to_numeric(v["fair_value"], errors="coerce")
    price = pd.to_numeric(v["price"], errors="coerce")
    debt = pr.fillna(0) > 0
    exp = 100 * fv / pr
    if price[debt].isna().any() or ((price[debt] - exp[debt]).abs() > 0.01).any():
        out.append("price must be 100 * fair_value / principal for debt rows")
    if price[~debt].notna().any():
        out.append("price must be NULL where there is no principal (equity)")
    isd = pd.to_numeric(v["is_debt"], errors="coerce")
    if not (isd == debt.astype(int)).all():
        out.append("is_debt must be 1 where principal > 0, else 0")
    return out
