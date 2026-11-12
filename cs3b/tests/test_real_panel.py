"""Real export must select periods, preserve evidence and abstain on ambiguity."""
import json
from pathlib import Path
import pandas as pd
import pytest
from services.signals.real_panel import classify, prior_fye, build_panel
from services.signals.pairing import pair
from creditwatch.panel import load_panel, validate


def test_prior_fiscal_year_end_handles_non_calendar_and_annual_filings():
    assert prior_fye('2026-06-30', '1231') == '2025-12-31'
    assert prior_fye('2026-06-30', '0331') == '2026-03-31'
    assert prior_fye('2026-09-30', '0930') == '2025-09-30'
    with pytest.raises(ValueError): prior_fye('2026-06-30', '9999')


def test_classification_prefers_source_and_does_not_guess_unknown():
    assert classify('Borrower', [{'column': 'enum', 'value': 'http://fasb.org/2026#DebtSecuritiesMember'}]) == ('DEBT', 'source_axis_or_enumeration')
    assert classify('Borrower First Lien Loan', []) == ('DEBT', 'identifier_text_inference')
    assert classify('Borrower', []) == ('UNKNOWN', 'unclassified')
    assert classify('Debt and Equity', []) == ('UNKNOWN', 'unclassified')
    assert classify('Borrower', [{'column': 'axis', 'value': 'Debt Securities'}, {'column': 'axis2', 'value': 'Common Stock'}]) == ('UNKNOWN', 'conflicting_source_types')


def example():
    rows = [dict(adsh='a', cik='1', name='Fictional', period='2026-06-30', ddate=d,
                 identifier='Borrower First Lien Loan', source_rows=str(i), n_conflicts=0,
                 fair_value=v, investment_type=None) for i, (d, v) in enumerate([
                     ('2024-12-31', 40), ('2025-12-31', 90), ('2026-06-30', 80)])]
    rows += [dict(rows[-1], adsh='b', source_rows='3')]
    holdings = pd.DataFrame(rows)
    sub = pd.DataFrame([dict(adsh=a, name='Fictional', period='2026-06-30', fye='1231') for a in ['a', 'b']])
    source = pd.DataFrame([{'adsh':r['adsh'], 'ddate':r['ddate'], 'Investment, Identifier Axis':r['identifier']} for r in rows])
    return holdings, sub, source


def test_old_year_is_excluded_not_summed_and_missing_prior_is_logged():
    holdings, sub, source = example()
    data, excluded, decisions = build_panel(holdings, ['a','b'], sub, source)
    assert len(data) == 2 and data.adsh.unique().tolist() == ['a']
    assert data.set_index('period_role').loc['prior', 'fair_value'] == 90
    assert data.set_index('period_role').loc['prior', 'source_rows'] == '1'
    assert excluded.exclusion_reason.value_counts().to_dict() == {'outside_selected_two_periods':1,'required_schedule_absent':1}
    assert not decisions.set_index('adsh').loc['b', 'admitted_to_two_period_panel']


def test_unknown_and_conflict_rows_remain_but_cannot_pair():
    holdings, sub, source = example()
    holdings.loc[2, 'n_conflicts'] = 1
    data, _, _ = build_panel(holdings, ['a'], sub, source)
    assert len(data) == 2
    assert not data[data.period_role == 'current'].pairing_eligible.iloc[0]
    assert pair(data).empty


def test_wrong_source_identity_fails_closed():
    holdings, sub, source = example()
    source.loc[1, 'Investment, Identifier Axis'] = 'Different loan'
    with pytest.raises(ValueError, match='Source row'): build_panel(holdings, ['a'], sub, source)


def test_saved_real_panel_contract_and_accounting():
    root = Path(__file__).resolve().parents[1]
    data = load_panel(root/'data/real/panel_2p.parquet')
    report = json.loads((root/'data/real/export_validation.json').read_text())
    exclusions = pd.read_csv(root/'data/real/excluded_rows.csv')
    assert validate(data) == []
    assert len(data) + len(exclusions) == 48940
    assert len(data) == report['rows']
    assert data.investment_type.notna().all()
    assert (data[data.period_role == 'current'].ddate == data[data.period_role == 'current'].period).all()
    assert (data[data.period_role == 'prior'].ddate == data[data.period_role == 'prior'].prior_fiscal_year_end).all()
    matched = pair(data)
    assert not matched.duplicated(['adsh','source_rows']).any()
    assert not matched.duplicated(['adsh','source_rows_prior']).any()
    assert (matched.investment_type == 'DEBT').all()
    assert (matched.n_conflicts == 0).all() and (matched.n_conflicts_prior == 0).all()


def test_completed_review_matches_final_panel_and_preserves_abstentions():
    import hashlib
    root = Path(__file__).resolve().parents[1]
    p = root / 'data/real/panel_2p.parquet'
    data = load_panel(p); matched = pair(data)
    review_dir = root / 'reports/heartbeat/real'
    metrics = json.loads((review_dir/'real_pair_metrics.json').read_text())
    assert hashlib.sha256(p.read_bytes()).hexdigest() == metrics['panel_sha256']
    reviewed = pd.read_csv(review_dir/'pair_review_completed.csv')
    assert len(reviewed) == 20 and reviewed.notes.notna().all()
    identities = set(zip(matched.adsh, matched.source_rows, matched.source_rows_prior))
    for row in reviewed.itertuples():
        present = (row.adsh, row.current_rows, row.prior_rows) in identities
        assert present != (row.verdict == 'WITHHOLD_TRUNCATED_IDENTITY')
    assert len(matched) == metrics['total_pairs']
    assert not matched.identifier_length_flag.any()


def test_source_review_preserves_null_values_and_does_not_invent_numbers():
    root = Path(__file__).resolve().parents[1]
    evidence = json.loads((root/'reports/heartbeat/real/pair_review_evidence.json').read_text())
    mapping = json.loads((root/'data/real/export_validation.json').read_text())['field_columns']
    for record in evidence:
        for side in ['current', 'prior']:
            source = record[side]
            assert all(r['adsh'] == record['adsh'] and r['ddate'] == source['date'] for r in source['source'])
            for field in ['fair_value', 'principal']:
                observed = next((float(r[c]) for r in source['source'] for c in mapping[field] if r.get(c)), None)
                assert observed == source[field]
