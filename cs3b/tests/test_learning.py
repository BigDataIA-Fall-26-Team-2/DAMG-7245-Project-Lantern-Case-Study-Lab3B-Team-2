"""Synthetic unit tests are separate from recorded live-agent acceptance."""
import json
from pathlib import Path
import sys

import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from creditwatch import audit, workspace
from creditwatch.llm import CacheMiss
from services.learning.governed import apply_correction
from services.learning.grading import borrower, grade
from services.learning.run import prepare, run_all, report, verify, publish
from services.agent.run import save


@pytest.fixture
def project(tmp_path):
    (tmp_path / 'params.yaml').write_text((ROOT / 'params.yaml').read_text())
    (tmp_path / 'data').symlink_to(ROOT / 'data', target_is_directory=True)
    (tmp_path / 'agent_seed').symlink_to(ROOT / 'agent_seed', target_is_directory=True)
    modeldir = tmp_path / 'services/agent'; modeldir.mkdir(parents=True)
    (modeldir / 'models.yaml').write_text((ROOT / 'services/agent/models.yaml').read_text())
    workspace.fresh_workspace(ROOT / 'agent_seed', tmp_path / 'agent')
    return tmp_path


@pytest.fixture
def prepared(project):
    bundle = project / 'recording'
    m = prepare(project, bundle, 'priya-fixture-token')
    m['provenance'] = 'synthetic-unit-test'
    save(bundle / 'manifest.json', m)
    return project, bundle, m


def test_authentication_and_idempotent_provenance(project):
    fx = ROOT / 'data/fixture'
    c = json.loads((fx / 'corrections.jsonl').read_text().splitlines()[0])
    users = json.loads((fx / 'users.json').read_text())
    ws = project / 'agent'; led = audit.Ledger()
    before = (ws / 'PRINCIPAL.md').read_text()
    assert apply_correction(ws, 'mandate_a', {**c, 'session_token': 'fake'}, users, led) == 'proposed'
    assert (ws / 'PRINCIPAL.md').read_text() == before
    assert apply_correction(ws, 'mandate_a', c, users, led) == 'written'
    assert apply_correction(ws, 'mandate_a', c, users, led) == 'already_written'
    assert len(led.find('memory_write')) == 1
    assert 'session_token' not in json.dumps(led.events)
    with pytest.raises(ValueError): apply_correction(ws, 'mandate_a', {**c, 'content': 'Different'}, users, led)
    with pytest.raises(PermissionError): apply_correction(ws, 'other_scope', c, users, led)


def test_freezes_only_rules_known_at_each_stage(prepared):
    root, bundle, m = prepared
    assert 'session_token' not in (bundle / 'manifest.json').read_text()
    assert (root / 'agent/PRINCIPAL.md').read_text() == m['stages'][0]['rules']
    for i, stage in enumerate(m['stages']):
        for j, correction in enumerate(m['corrections']):
            assert (correction['message_id'] in stage['rules']) == (j < i)
    for stage in m['stages']:
        assert 'Northgate' not in stage['contexts']['mandate_a']
        assert 'Harbor State' not in stage['contexts']['mandate_b']


class FakeProvider:
    def __call__(self, request):
        msgs = request['input']['messages']
        done = {m.get('name') for m in msgs if m.get('role') == 'tool'}
        evidence = request['input']['brief']['materiality']
        tool, args = None, {}
        if 'mandate_profile' not in done:
            tool, args = 'mandate_profile', {'scope': 'mandate_a' if 'Harbor' in evidence['profile']['client'] else 'mandate_b'}
        elif 'bdc_signals' not in done:
            tool, args = 'bdc_signals', {'scope': 'public'}
        context = request['instructions']
        learned = {mid: mid in context for mid in ['msg-101', 'msg-102', 'msg-103', 'msg-104']}
        held = evidence['profile']['positions']
        lines = ['Your exposure: ' + ', '.join(f'{b} ${v:g}m' for b, v in held.items())] if learned['msg-103'] else []
        for s in evidence['signals']:
            if s['name'] not in held: continue
            name = borrower(s['identifier'])
            if s['rule'] == 'MARKDOWN':
                note = f"{name}: marked down {s['before']-s['after']:g}" + (' points' if learned['msg-102'] else '%')
            else: note = name + ': ' + s['rule']
            if learned['msg-104']: note += ' [' + s['adsh'] + ']'
            lines.append(note)
        for h in evidence['holdings']:
            if h['name'] in held and (h.get('pik_rate') or 0) > 0:
                lines.append(borrower(h['identifier']) + (': PIK unchanged or present at origination.' if learned['msg-101'] else ': PIK (watch)'))
        return {'tool': tool, 'args_json': json.dumps(args), 'text': '\n'.join(lines),
                'rationale': 'Synthetic unit test only', 'tokens_in': 20, 'tokens_out': 20,
                'usd': 0, 'provider_response_id': 'synthetic-response'}


def test_record_replay_and_regression_reporting(prepared, monkeypatch):
    _, bundle, m = prepared
    rows = run_all(bundle, 'record', FakeProvider())
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: pytest.fail('Replay used network'))
    replayed, verification = verify(bundle)
    assert rows == replayed and verification['identical']
    pairs, summary = report(m, rows)
    assert all(r['before_pass'] == 0 and r['after_pass'] == 2 for r in summary['corrections'])
    assert all(r['regressions'] == 0 for r in summary['corrections'])
    rows[4]['grades']['checks']['msg-101'] = False
    _, changed = report(m, rows)
    assert changed['corrections'][1]['regressions'] == 1
    with pytest.raises(ValueError): publish(bundle.parent, bundle, rows)


def test_empty_answers_never_pass(prepared):
    _, _, m = prepared
    for evidence in m['evidence'].values():
        assert not any(grade('', evidence)['checks'].values())


def test_replay_cache_miss_is_not_live_fallback(prepared):
    _, bundle, _ = prepared
    with pytest.raises(CacheMiss): run_all(bundle, 'replay')


def test_bad_session_does_not_build_manifest(project):
    with pytest.raises(PermissionError): prepare(project, project / 'recording', 'bad-token')
    assert not (project / 'recording/manifest.json').exists()


def test_real_learning_recording_replays_offline(tmp_path, monkeypatch):
    import shutil
    source = ROOT / 'evals/recordings/learning'
    if not (source / 'verification.json').exists():
        pytest.skip('Live learning recording is not complete yet')
    bundle = tmp_path / 'live-copy'
    shutil.copytree(source, bundle)
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: pytest.fail('Replay contacted provider'))
    manifest = json.loads((bundle / 'manifest.json').read_text())
    assert manifest['provenance'] == 'openai-live'
    results, checked = verify(bundle)
    assert len(results) == 10 and checked['provider_calls_during_replay'] == 0
    assert all(r['isolated'] for r in results)
    assert all(e['provider_response_id'].startswith('resp_') for r in results for e in r['model_calls'])


def test_grader_rejects_percent_and_missing_citations(prepared):
    _, _, m = prepared
    evidence = m['evidence']['mandate_a']
    lines = []
    for s in evidence['signals']:
        if s['name'] in evidence['profile']['positions']:
            lines.append(borrower(s['identifier']) + ': marked down 7.5%')
    result = grade('\n'.join(lines), evidence)
    assert not result['checks']['msg-102'] and not result['checks']['msg-104']


def test_hyphenated_points_and_short_names_are_recognized(prepared):
    _, _, m = prepared
    evidence = m['evidence']['mandate_a']
    lines = []
    for s in evidence['signals']:
        if s['name'] not in evidence['profile']['positions']: continue
        name = borrower(s['identifier']).split()[0]
        body = f"{s['before']-s['after']:g}-point decline" if s['rule'] == 'MARKDOWN' else s['rule']
        lines.append(f"{name}: {body} [{s['adsh']}]")
    checks = grade('\n'.join(lines), evidence)['checks']
    assert checks['msg-102'] and checks['msg-104']


def test_pre_written_rules_cannot_gain_provenance(prepared):
    root, bundle, m = prepared
    m['provenance'] = 'openai-live'
    save(bundle / 'manifest.json', m)
    (root / 'agent/PRINCIPAL.md').write_text(m['stages'][1]['rules'])
    with pytest.raises(ValueError, match='memory_write'):
        publish(root, bundle, [])


def test_planning_cannot_pass_as_a_completed_note(prepared):
    _, _, m = prepared
    evidence = m['evidence']['mandate_a']
    checked = grade('Task class: client note. Lead with exposure of $42m. Ready to draft.', evidence)
    assert not checked['completed_note'] and not any(checked['checks'].values())


def test_exposure_must_be_in_opening_sentence(prepared):
    _, _, m = prepared
    evidence = m['evidence']['mandate_a']
    assert not grade('Mandate confirmed. Later lead with exposure of $42m.', evidence)['checks']['msg-103']
    assert grade('Your exposure is $95.5m.', evidence)['checks']['msg-103']
