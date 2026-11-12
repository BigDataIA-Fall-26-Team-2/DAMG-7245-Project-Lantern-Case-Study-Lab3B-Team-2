"""Conservative, transparent fixture checks; not a semantic or causal proof."""
import re
from creditwatch import policy


def borrower(identifier):
    parts = identifier.split(' | ')
    return parts[1] if len(parts) > 1 else identifier.split(',')[0]


def matching_lines(text, identifier):
    name = policy.words(borrower(identifier)).strip()
    # Fixture borrowers have distinctive first names; accept shortened prose names.
    alias = ' ' + name.split()[0] + ' '
    return [line for line in text.splitlines() if name in policy.words(line) or alias in policy.words(line)]


def grade(text, evidence):
    profile = evidence['profile']
    held = profile['positions']
    sig = [s for s in evidence['signals'] if s['name'] in held]
    marks = [s for s in sig if s['rule'] == 'MARKDOWN']
    pik_keys = {(s['adsh'], str(s['row'])) for s in sig if s['rule'] == 'PIK_UP'}
    background = [h for h in evidence['holdings'] if h['name'] in held and (h.get('pik_rate') or 0) > 0
                  and (h['adsh'], str(h['source_rows'])) not in pik_keys]
    # No empty/vacuous passes: each expected observation needs a matching line.
    coverage = bool(sig) and all(matching_lines(text, s['identifier']) for s in sig)
    pik_ok = bool(background)
    for h in background:
        lines = matching_lines(text, h['identifier'])
        pik_ok &= bool(lines) and any(re.search(r'unchanged|origination|originated|not.{0,35}(stress|flag|increase)|no.{0,20}(increase|stress)', l, re.I) for l in lines)
        pik_ok &= not any(re.search(r'PIK\s*\(watch\)', l, re.I) for l in lines)
    points_ok = bool(marks)
    for s in marks:
        lines = matching_lines(text, s['identifier'])
        delta = s['before'] - s['after']
        expected = rf'{re.escape(f"{delta:g}")}0*[-\s]+(?:price\s+)?(?:points?|pts)\b'
        points_ok &= any(re.search(expected, l, re.I) for l in lines)
        points_ok &= not any(re.search(r'(?:down|fell|declin\w*|drop\w*|marked\w*)\s+(?:by\s+)?\d+(?:\.\d+)?\s*%', l, re.I) for l in lines)
    first = next((l.strip(' #*-') for l in text.splitlines() if l.strip()), '')
    first = re.split(r'[.!?](?:\s|$)', first, maxsplit=1)[0]
    opening_numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", first.replace(',', ''))]
    exposure_ok = bool(re.search(r'exposure|holds|holdings|position', first, re.I)) and any(
        abs(n - v) < .001 for n in opening_numbers for v in [*held.values(), sum(held.values())])
    citations_ok = coverage and all(any(s['adsh'] in l for l in matching_lines(text, s['identifier'])) for s in sig)
    checks = {'msg-101': bool(pik_ok and coverage), 'msg-102': bool(points_ok and coverage),
              'msg-103': bool(exposure_ok), 'msg-104': bool(citations_ok)}
    planning = bool(re.search(r'ready to draft|Task class:|Evidence in hand is sufficient|Needed evidence is sufficient to draft', text, re.I))
    if planning:
        checks = {mid: False for mid in checks}
    return {'checks': checks, 'signal_coverage': coverage, 'completed_note': not planning and bool(text.strip()),
            'rubric': 'v3: fixture alias/points checks; opening sentence exposure; explicit planning-only responses fail; human semantic review required'}
