"""Evidence-preserving selection and classification for a real CS2B export."""
import json
import re
from datetime import date
import pandas as pd

TYPE_COLUMNS = ['Investment Type Axis', 'Investment, Type [Extensible Enumeration]',
                'Financial Instrument Axis', 'InvestmentSubType', 'Class of Stock Axis']
DEBT = re.compile(r'\b(?:debt|loans?|liens?|notes?|bonds?|unitranche|revolv\w*|debentures?)\b', re.I)
EQUITY = re.compile(r'\b(?:equity|stock|shares?|warrants?|membership interests?|partnership interests?|preferred units?|common units?)\b', re.I)
OTHER = re.compile(r'\b(?:derivative|swap|forward|real estate|property|properties)\b', re.I)


def text_type(text):
    # Split an XBRL member's CamelCase spelling; do not inspect URL hostname text.
    text = str(text).split('#')[-1]
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    debt, equity = bool(DEBT.search(text)), bool(EQUITY.search(text))
    if debt and equity:
        return 'UNKNOWN'
    if debt:
        return 'DEBT'
    if equity:
        return 'EQUITY'
    if OTHER.search(text):
        return 'OTHER'
    return 'UNKNOWN'


def classify(identifier, evidence):
    """Source axes/enumerations take priority; a text fallback is labelled inferred."""
    source = {text_type(e['value']) for e in evidence} - {'UNKNOWN'}
    if len(source) > 1:
        return 'UNKNOWN', 'conflicting_source_types'
    if source:
        return source.pop(), 'source_axis_or_enumeration'
    inferred = text_type(identifier)
    return inferred, 'identifier_text_inference' if inferred != 'UNKNOWN' else 'unclassified'


def prior_fye(period, fye):
    current = date.fromisoformat(str(period))
    fye = str(fye).zfill(4)
    month, day = int(fye[:2]), int(fye[2:])
    year = current.year if (month, day) < (current.month, current.day) else current.year - 1
    return date(year, month, day).isoformat()


def build_panel(holdings, admitted, sub, source):
    """Return the usable panel and a complete accounting of excluded rows/filings.

    No values from different dates are summed. Unknown types and conflicting
    holdings remain visible in the panel but are ineligible for automatic pairing.
    """
    candidate = holdings[holdings.adsh.isin(set(admitted))].copy()
    metadata = sub.set_index('adsh')
    selected, excluded, decisions = [], [], []
    for adsh, group in candidate.groupby('adsh', sort=True):
        period = str(metadata.loc[adsh, 'period'])
        expected = prior_fye(period, metadata.loc[adsh, 'fye'])
        dates = set(group.ddate.dropna())
        available = period in dates and expected in dates
        decisions.append(dict(adsh=adsh, name=metadata.loc[adsh, 'name'], current_date=period,
                              prior_fiscal_year_end=expected, available_dates=';'.join(sorted(dates)),
                              admitted_to_two_period_panel=available,
                              reason='both_schedules_present' if available else 'required_schedule_absent'))
        for row in group.to_dict('records'):
            if not available or row['ddate'] not in {period, expected}:
                excluded.append({**row, 'exclusion_reason': 'required_schedule_absent' if not available else 'outside_selected_two_periods'})
                continue
            row['period_role'] = 'current' if row['ddate'] == period else 'prior'
            row['prior_fiscal_year_end'] = expected
            evidence = []
            for index in map(int, row['source_rows'].split(';')):
                raw = source.loc[index]
                if raw['adsh'] != adsh or raw['Investment, Identifier Axis'] != row['identifier'] or str(raw['ddate']) != str(row['ddate']):
                    raise ValueError('Source row does not belong to the exported holding')
                for column in TYPE_COLUMNS:
                    value = raw.get(column)
                    if pd.notna(value):
                        item = {'column': column, 'value': str(value)}
                        if item not in evidence:
                            evidence.append(item)
            kind, basis = classify(row['identifier'], evidence)
            row['investment_type'] = kind
            row['classification_basis'] = basis
            row['classification_evidence'] = json.dumps(evidence, sort_keys=True)
            row['identifier_length_flag'] = len(str(row['identifier'])) >= 255
            row['pairing_eligible'] = kind == 'DEBT' and int(row.get('n_conflicts', 0)) == 0 and not row['identifier_length_flag']
            row['pairing_exclusion_reason'] = ('source_value_conflict' if int(row.get('n_conflicts', 0)) else
                                               'not_classified_as_debt' if kind != 'DEBT' else
                                               'long_identifier_requires_source_review' if row['identifier_length_flag'] else '')
            selected.append(row)
    return pd.DataFrame(selected), pd.DataFrame(excluded), pd.DataFrame(decisions)
