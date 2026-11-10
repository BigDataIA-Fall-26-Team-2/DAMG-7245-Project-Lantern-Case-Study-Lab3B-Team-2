"""Export a two-period panel from the Lab 2B baseline (lookthrough) for Case Study 3B.

    python tools/export_panel_from_lab2b.py ../cs2b data/panel_2p.parquet

Runs the Lab 2B baseline on the release in ../cs2b/params.yaml and keeps BOTH schedules of every
admitted filing. If your Case Study 2B pipeline differs from the kit's baseline (it should), write
your own export with creditwatch.panel.from_holdings and check it with creditwatch.panel.validate.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from creditwatch import panel  # noqa: E402


def main(cs2b, out):
    cs2b = Path(cs2b).resolve()
    sys.path.insert(0, str(cs2b / "src"))
    from lookthrough import clean, paths, pipeline        # the Lab 2B kit
    P = paths.load_params(cs2b)
    B = pipeline.run_baseline(paths.release_dir(P, cs2b), P["reconcile"]["tolerance"])
    admitted = B["rec"].loc[B["rec"]["admitted"], "adsh"]
    both, _ = clean.apply_rules(B["holdings"], [clean.rule_totals, clean.rule_cash])  # BOTH schedules
    p = panel.from_holdings(both, admitted)
    problems = panel.validate(p)
    out = Path(out); out.parent.mkdir(parents=True, exist_ok=True)
    (p.to_parquet(out, index=False) if out.suffix == ".parquet" else p.to_csv(out, index=False))
    print(f"{len(p)} rows from {p['adsh'].nunique()} admitted filings -> {out}")
    for x in problems:
        print("  check:", x)
    return problems


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
