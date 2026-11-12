"""Prepare reproducible source evidence for manual real-panel pair review.

Does not assign review verdicts. Re-running preserves a separate completed review.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from creditwatch.panel import load_panel, validate
from services.signals.pairing import pair


def prepare(panel_path, source_dir, output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if (output/'pair_review_completed.csv').exists():
        raise ValueError('Completed review exists; choose a fresh output directory to preserve evidence.')
    data=load_panel(panel_path)
    if validate(data):raise ValueError(validate(data))
    matched=pair(data)
    short=matched.identifier.str.len().lt(255)
    categories=[('source_classified_exact',matched[short & matched.identifier.eq(matched.identifier_prior) & matched.classification_basis.eq('source_axis_or_enumeration')],6),
                ('text_classified_exact',matched[short & matched.identifier.eq(matched.identifier_prior) & matched.classification_basis.eq('identifier_text_inference')],6),
                ('normalized_identifier',matched[short & matched.identifier.ne(matched.identifier_prior)],6),
                ('long_identifier',matched[~short],2)]
    chosen=[]
    for label,frame,count in categories:
        # Fixed-seed sample within declared strata; includes long-identifier risk cases.
        for row in frame.sample(n=min(count,len(frame)),random_state=31).to_dict('records'):
            row['review_stratum']=label;chosen.append(row)
    source=Path(source_dir)/'soi.tsv'
    expected=json.loads((Path(panel_path).parent/'export_validation.json').read_text())['source_hashes']['soi.tsv']
    actual=hashlib.sha256(source.read_bytes()).hexdigest()
    if actual!=expected:raise ValueError('Source hash differs from panel export')
    cols=['adsh','cik','name','ddate','inlineurl','Investment, Identifier Axis','Investment Type Axis',
          'Investment, Type [Extensible Enumeration]','Investment Owned, Fair Value',
          'Investment Owned, Balance, Principal Amount','Investment Maturity Date','Investment, Interest Rate, Paid in Kind']
    export = json.loads((Path(panel_path).parent/'export_validation.json').read_text())
    cols = sorted(set(cols + [c for values in export['field_columns'].values() for c in values]))
    raw=pd.read_csv(source,sep='\t',dtype=str,usecols=cols,keep_default_na=False)
    records=[]
    for i,row in enumerate(chosen,1):
        sides={}
        for side,suffix in [('current',''),('prior','_prior')]:
            indices=list(map(int,row['source_rows'+suffix].split(';')))
            evidence=raw.iloc[indices].copy()
            assert evidence.adsh.eq(row['adsh']).all()
            assert evidence['Investment, Identifier Axis'].eq(row['identifier'+suffix]).all()
            evidence.insert(0,'soi_row',indices)
            sides[side]=dict(date=row['ddate'+suffix],identifier=row['identifier'+suffix],
                source_rows=row['source_rows'+suffix],fair_value=row['fair_value'+suffix],
                principal=row['principal'+suffix],source=evidence.to_dict('records'))
        records.append(dict(review_id=f'real-pair-{i:02}',adsh=row['adsh'],name=row['name'],
                            stratum=row['review_stratum'],classification_basis=row['classification_basis'],**sides))
    # pandas converts missing numeric values to valid JSON nulls.
    (output/'pair_review_evidence.json').write_text(pd.Series(records).to_json(orient='values',indent=2)+'\n')
    pd.DataFrame([dict(review_id=r['review_id'],adsh=r['adsh'],name=r['name'],stratum=r['stratum'],
        current_identifier=r['current']['identifier'],prior_identifier=r['prior']['identifier'],
        current_rows=r['current']['source_rows'],prior_rows=r['prior']['source_rows'],
        review_verdict='',review_notes='') for r in records]).to_csv(output/'pair_review_template.csv',index=False)
    cur=data[data.period_role.eq('current')]
    coverage=cur.groupby(['adsh','name']).agg(current_holdings=('identifier','size'),eligible_current_debt=('pairing_eligible','sum'))
    coverage['matched_current_debt']=matched.groupby(['adsh','name']).size()
    coverage['matched_current_debt']=coverage.matched_current_debt.fillna(0).astype(int)
    coverage['eligible_unpaired']=coverage.eligible_current_debt-coverage.matched_current_debt
    coverage.reset_index().to_csv(output/'real_pair_coverage.csv',index=False)
    summary=dict(total_pairs=len(matched),filings_with_pairs=int(matched.adsh.nunique()),
        current_holdings=len(cur),eligible_current_debt=int(cur.pairing_eligible.sum()),
        eligible_debt_pairing_rate=len(matched)/int(cur.pairing_eligible.sum()),
        unknown_current_holdings=int(cur.investment_type.eq('UNKNOWN').sum()),
        review_sample_size=len(records),review_sample_filings=len({r['adsh'] for r in records}),
        sample_selection='Seed 31 within strata: 6 source-classified exact, 6 text-classified exact, 6 normalized identifiers, 2 long identifiers; not a population accuracy estimate.',
        source_soi_sha256=actual,review_status='evidence prepared; verdicts require inspection',
        limits='Conservative matching leaves rate/maturity text variants and uncertain types unpaired. Coverage is not recall. No real-data ground-truth event registry exists.')
    (output/'real_pair_metrics.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
    return summary


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('panel');ap.add_argument('source');ap.add_argument('--output',default='reports/heartbeat/real')
    args=ap.parse_args();prepare(args.panel,args.source,args.output)
