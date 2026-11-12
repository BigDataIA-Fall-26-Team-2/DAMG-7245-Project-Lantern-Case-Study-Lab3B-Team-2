"""Export and validate a source-backed two-period panel from Lab 2B.

python tools/export_panel_from_lab2b.py /path/to/cs2b data/real/panel_2p.parquet
Exclusions and classification evidence are written alongside the panel. The raw
Lab 2B inputs, original holdings and fixture configuration are never modified.
"""
import hashlib
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from creditwatch import panel
from services.signals.real_panel import TYPE_COLUMNS, build_panel


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main(cs2b, out):
    cs2b, out = Path(cs2b).resolve(), Path(out)
    sys.path.insert(0, str(cs2b / 'src'))
    from lookthrough import clean, load, paths, pipeline
    settings = paths.load_params(cs2b)
    release = paths.release_dir(settings, cs2b)
    base = pipeline.run_baseline(release, settings['reconcile']['tolerance'])
    admitted = base['rec'].loc[base['rec']['admitted'], 'adsh']
    holdings, cleaning = clean.apply_rules(base['holdings'], [clean.rule_totals, clean.rule_cash])
    columns = ['adsh', 'ddate', 'Investment, Identifier Axis'] + TYPE_COLUMNS
    source = load.load_soi(release, columns).set_index('soi_row')
    data, excluded, decisions = build_panel(holdings, admitted, base['sub'], source)
    problems = panel.validate(data)
    if problems:
        raise ValueError('Export failed validation: ' + '; '.join(problems))
    if data.duplicated(['adsh', 'ddate', 'identifier']).any():
        raise ValueError('Duplicate holding remains after exact period selection')
    out.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(out, index=False) if out.suffix == '.parquet' else data.to_csv(out, index=False)
    excluded.to_csv(out.parent / 'excluded_rows.csv', index=False)
    decisions.to_csv(out.parent / 'filing_selection.csv', index=False)
    cleaning.to_csv(out.parent / 'source_cleaning.csv', index=False)
    report = dict(validation=problems, rows=len(data), filings=int(data.adsh.nunique()),
        baseline_admitted_filings=len(admitted), excluded_rows=len(excluded),
        exclusion_reasons=excluded.exclusion_reason.value_counts().to_dict(),
        classifications=data.investment_type.value_counts().to_dict(),
        classification_bases=data.classification_basis.value_counts().to_dict(),
        pairing_eligible_rows=int(data.pairing_eligible.sum()), source_conflict_rows=int((data.n_conflicts > 0).sum()),
        field_columns=base['colmap'], long_identifier_rows=int(data.identifier_length_flag.sum()),
        source_release=settings['release'], source_manifest=json.loads((cs2b / 'data/manifest.json').read_text()),
        source_hashes={name: digest(release / name) for name in ['soi.tsv', 'datasets/sub.tsv']},
        panel_sha256=digest(out),
        policy='Select current and prior fiscal year-end from SUB, exclude unavailable two-period filings with receipts, retain unknown/conflicting holdings but abstain from pairing. Classification inferred from identifier text is explicitly labelled, not asserted as an original source type.')
    (out.parent / 'export_validation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
