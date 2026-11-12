"""Conservative, one-to-one within-filing pairing; ambiguous keys abstain."""
import re
import unicodedata
import pandas as pd


def stable_identifier(value):
    text = unicodedata.normalize('NFKC', str(value)).casefold()
    # Strip only standalone rate/date segments, not borrower or tranche numbers.
    pieces = [p.strip() for p in text.split('|')]
    kept = []
    for piece in pieces:
        if re.fullmatch(r'(?:s|sofr|libor)\s*\+\s*\d+(?:\.\d+)?%\s*(?:\(\d+(?:\.\d+)?%\))?', piece):
            continue
        if re.fullmatch(r'\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2}', piece):
            continue
        kept.append(re.sub(r'\s+', ' ', piece))
    return ' | '.join(kept)


def pair(panel):
    """Output follows pair_exact's suffix contract, retaining both identifiers."""
    keys = ['adsh', 'cik', 'investment_type', '_identity']
    p = panel.copy()
    p['_identity'] = p.identifier.map(stable_identifier)
    cur = p[p.period_role == 'current'].copy()
    prior = p[p.period_role == 'prior'].copy()
    # Never make a many-to-many join or guess between sibling loans.
    cur = cur[~cur.duplicated(keys, keep=False) & cur._identity.ne('')]
    prior = prior[~prior.duplicated(keys, keep=False) & prior._identity.ne('')]
    result = cur.merge(prior, on=keys, suffixes=('', '_prior'), validate='one_to_one')
    return result.drop(columns='_identity').sort_values(['adsh', 'source_rows']).reset_index(drop=True)
