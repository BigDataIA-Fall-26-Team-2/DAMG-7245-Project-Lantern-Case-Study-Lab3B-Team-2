"""Lab 29 acceptance: configured policy, exact approval and durable redacted audit."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path

import pytest
import yaml
from test_mcp_tools import runtime, email, entry, success, approve
from creditwatch import approvals, audit, channel, clock
from services.mcp.action_policy import ActionPolicy
from services.mcp.errors import ApprovalRequiredError
from services.mcp.runtime import read, save
from services.mcp.server import ROOT, create_runtime


@pytest.fixture
def logged(runtime, tmp_path):
    runtime.ledger = audit.Ledger(tmp_path / 'actions.jsonl', clock=runtime.now)
    return runtime


def draft_and_token(r):
    draft = success(r, 'draft_email', email(r))
    token = approve(r, 'send_email', {'draft_id': draft['draft_id']})
    return draft, {'scope': 'mandate_a', 'draft_id': draft['draft_id'], 'approval_token': token}


@pytest.mark.parametrize('change,rule', [
    ({'body': 'Northgate has been adding to Hotel.'}, 'R-OTHER-MANDATE'),
    ({'body': 'Ref NG\u200b-PC 9902.'}, 'R-OTHER-MANDATE'),
    ({'body': 'NGM\u200b-Quillwort-8830'}, 'R-OTHER-MANDATE'),
    ({'body': 'Ironwood Data Systems is refinancing.'}, 'R-RESTRICTED'),
    ({'subject': 'Ironwood Data Systems'}, 'R-RESTRICTED'),
    ({'attachments': ['Ironwood Data Systems']}, 'R-RESTRICTED'),
    ({'to': ['cfo@crestlineroofing.example']}, 'R-BORROWER'),
    ({'to': ['cio@harborstate.example', 'me@gmail.example']}, 'R-NOT-CONTACT'),
    ({'to': ['real@gmail.com']}, 'R-FIXTURE-EMAIL'),
])
def test_blocked_content_has_reviewable_reason(logged, change, rule):
    r = logged
    result = r.call('draft_email', {**email(r), **change})
    assert result['error']['code'] == 'POLICY_DENIED'
    assert not list(r.outbox.glob('*.json'))
    saved = [json.loads(line) for line in Path(r.ledger.path).read_text().splitlines()]
    block = next(e for e in saved if e['kind'] == 'policy_block')
    assert block['rule_id'] == rule and block['decision'] == 'blocked'
    assert all('body' not in e and 'approval_token' not in e for e in saved)


@pytest.mark.parametrize('field,value', [
    ('to', ['cio@harborstate.example', 'credit.pm@harborstate.example']),
    ('subject', 'New subject'), ('body', 'Changed body'), ('attachments', ['new-file.txt']),
])
def test_edited_email_is_blocked_and_reapproval_succeeds(logged, field, value):
    r = logged
    draft, args = draft_and_token(r)
    draft[field] = value
    save(r.file('drafts', draft['draft_id']), draft)
    assert r.call('send_email', args)['error']['code'] == 'APPROVAL_REQUIRED'
    assert r.ledger.find('policy_block')[-1]['reason'] == 'payload_changed'
    assert not list(r.outbox.glob('*.json'))
    args['approval_token'] = approve(r, 'send_email', {'draft_id': draft['draft_id']})
    result = success(r, 'send_email', args)
    stored = read(r.outbox / (result['outbox_message_id'] + '.json'))
    assert stored[field] == value
    assert success(r, 'send_email', args)['status'] == 'already_sent'
    assert len(list(r.outbox.glob('*.json'))) == 1
    # Re-open the file independently: reasons survive loss of the ledger object.
    text = Path(r.ledger.path).read_text()
    events = [json.loads(line) for line in text.splitlines()]
    assert any(e.get('reason') == 'payload_changed' for e in events)
    assert any(e['kind'] == 'mock_send' for e in events)
    assert args['approval_token'] not in text and email(r)['body'] not in text


@pytest.mark.parametrize('case,reason', [('missing', 'missing_token'), ('malformed', 'malformed'),
    ('wrong_person', 'wrong_approver'), ('expired', 'expired'), ('no_grant', 'missing_human_grant')])
def test_invalid_approval_reasons(logged, case, reason):
    r = logged
    draft, args = draft_and_token(r)
    if case == 'missing': args['approval_token'] = ''
    elif case == 'malformed': args['approval_token'] = 'not-a-token'
    elif case == 'wrong_person':
        args['approval_token'] = approvals.issue_token(r.envelope('send_email', draft), 'tom', r.now().timestamp())
    elif case == 'expired':
        now = r.now(); r.now = lambda: now + timedelta(minutes=30)
    elif case == 'no_grant':
        for file in (r.state / 'grants').glob('*.json'): file.unlink()
    assert r.call('send_email', args)['error']['code'] == 'APPROVAL_REQUIRED'
    assert r.ledger.find('policy_block')[-1]['reason'] == reason
    assert not list(r.outbox.glob('*.json'))


def test_changed_draft_cannot_be_granted_from_stale_request(logged):
    r = logged
    draft = success(r, 'draft_email', email(r))
    request = success(r, 'request_approval', {'action': 'send_email', 'payload': {'draft_id': draft['draft_id']}})
    draft['body'] += ' Updated after the request'
    save(r.file('drafts', draft['draft_id']), draft)
    with pytest.raises(ApprovalRequiredError): r.grant(request['request_id'], request['payload_hash'])
    assert r.ledger.find('policy_block')[-1]['reason'] == 'payload_changed'
    assert not list((r.state / 'grants').glob('*.json'))


def test_send_rechecks_policy_after_approval(logged):
    r = logged
    draft, args = draft_and_token(r)
    r.registry = {**r.registry, 'restricted': ['Draft for review']}
    assert r.call('send_email', args)['error']['code'] == 'POLICY_DENIED'
    assert r.ledger.find('policy_block')[-1]['rule_id'] == 'R-RESTRICTED'
    assert not list(r.outbox.glob('*.json'))


@pytest.mark.parametrize('field,value', [('note', 'Edited note'), ('citations', ['changed:row:2']),
                                       ('bdc', 'FIXTURE HOTEL SENIOR LENDING')])
def test_watchlist_exact_fields_and_cross_action_tokens(logged, field, value):
    r = logged
    payload = {'scope': 'mandate_a', 'entry': entry(r)}
    before = (r.directory / 'WATCHLIST.md').read_bytes()
    token = approve(r, 'watchlist_write', payload)
    changed = {**payload, 'entry': {**payload['entry'], field: value}, 'approval_token': token}
    assert r.call('watchlist_write', changed)['error']['code'] == 'APPROVAL_REQUIRED'
    assert (r.directory / 'WATCHLIST.md').read_bytes() == before
    draft = success(r, 'draft_email', email(r))
    assert r.call('send_email', {'scope': 'mandate_a', 'draft_id': draft['draft_id'], 'approval_token': token})['error']['code'] == 'APPROVAL_REQUIRED'
    assert success(r, 'watchlist_write', {**payload, 'approval_token': token})['status'] == 'written'


@pytest.mark.parametrize('mutation', ['class', 'send_auto', 'watchlist_auto', 'missing'])
def test_unsafe_or_incomplete_configuration_fails_startup(mutation):
    config = yaml.safe_load((ROOT / 'params.yaml').read_text())['action_policy']
    if mutation == 'class': config['tool_classes']['send_email'] = 'READ'
    elif mutation == 'send_auto': config['class_policies']['EXTERNAL_SEND'] = 'auto'
    elif mutation == 'watchlist_auto': config['overrides']['watchlist_write'] = 'auto'
    else: del config['tool_classes']['draft_email']
    with pytest.raises(ValueError): ActionPolicy(config)


def test_server_reads_config_from_yaml_and_enforces_it(logged, tmp_path):
    r = logged
    root = tmp_path / 'configured'; root.mkdir()
    config = yaml.safe_load((ROOT / 'params.yaml').read_text())
    config['action_policy']['class_policies']['DRAFT'] = 'forbidden'
    (root / 'params.yaml').write_text(yaml.safe_dump(config))
    (root / 'data').symlink_to(ROOT / 'data', target_is_directory=True)
    configured = create_runtime(session=r.session, ledger=r.ledger, mandates=r.mandates,
                                root=root, workspace=r.workspace, outbox=r.outbox)
    assert configured.call('draft_email', email(r))['error']['code'] == 'POLICY_DENIED'
    assert r.ledger.find('policy_block')[-1]['reason'] == 'action_forbidden'


def test_forbidden_send_blocks_request_even_for_existing_draft(logged):
    r = logged
    draft = success(r, 'draft_email', email(r))
    config = yaml.safe_load((ROOT / 'params.yaml').read_text())['action_policy']
    config['overrides']['send_email'] = 'forbidden'
    r.action_policy = ActionPolicy(config)
    response = r.call('request_approval', {'action': 'send_email', 'payload': {'draft_id': draft['draft_id']}})
    assert response['error']['code'] == 'POLICY_DENIED'
    assert not list((r.state / 'requests').glob('*.json'))
