"""Within-filing credit signals: this period's schedule against
the prior fiscal year-end schedule in the SAME filing."""
import pandas as pd

KEY = ["adsh", "identifier"]


def pair_exact(panel):
    """Baseline pairing: same filing, identical identifier.
    It misses identifiers that embed a coupon or maturity."""
    cur = panel[panel["period_role"] == "current"]
    pri = panel[panel["period_role"] == "prior"]
    return cur.merge(pri, on=KEY, suffixes=("", "_prior"))


def price(fv, principal):
    """A mark as a price: 100 x fair value / principal."""
    return 100 * fv / principal.where(principal > 0)


def _out(pairs, mask, rule, before, after):
    p = pairs[mask]
    return pd.DataFrame({
        "adsh": p["adsh"], "name": p["name"], "rule": rule,
        "identifier": p["identifier"], "row": p["source_rows"],
        "prior_row": p["source_rows_prior"],
        "before": before[mask], "after": after[mask]})


def markdowns(pairs, points=5.0):
    p0 = price(pairs["fair_value_prior"],
               pairs["principal_prior"])
    p1 = price(pairs["fair_value"], pairs["principal"])
    return _out(pairs, (p0 - p1) >= points, "MARKDOWN", p0, p1)


def pik_increases(pairs, points=0.5):
    k0 = pairs["pik_rate_prior"].fillna(0) * 100   # percent
    k1 = pairs["pik_rate"].fillna(0) * 100
    return _out(pairs, (k1 - k0) >= points, "PIK_UP", k0, k1)


def extensions(pairs, months=6):
    m0 = pd.to_datetime(pairs["maturity_prior"], errors="coerce")
    m1 = pd.to_datetime(pairs["maturity"], errors="coerce")
    longer = (m1 - m0).dt.days / 30.44 >= months
    return _out(pairs, longer, "EXTENDED",
                m0.dt.strftime("%Y-%m-%d"),
                m1.dt.strftime("%Y-%m-%d"))


def find_signals(panel, m, pair=pair_exact):
    """m: heartbeat.materiality from params.yaml. Pass your own
    pairing function as `pair`; the rules stay the same."""
    pairs = pair(panel)
    out = pd.concat([
        markdowns(pairs, m["markdown_points"]),
        pik_increases(pairs, m["pik_points"]),
        extensions(pairs, m["extension_months"])])
    return out.sort_values(["adsh", "rule", "row"]) \
        .reset_index(drop=True)


def pairing_report(panel, pairs):
    """Per filing: debt holdings this period, and how many the
    pairing found in the prior schedule."""
    cur = panel[(panel["period_role"] == "current")
                & (panel["principal"] > 0)]
    got = pairs[pairs["principal"] > 0].groupby("adsh").size()
    r = cur.groupby(["adsh", "name"]).size().rename("debt_holdings")
    r = r.reset_index()
    r["paired"] = r["adsh"].map(got).fillna(0).astype(int)
    r["unpaired"] = r["debt_holdings"] - r["paired"]
    return r
