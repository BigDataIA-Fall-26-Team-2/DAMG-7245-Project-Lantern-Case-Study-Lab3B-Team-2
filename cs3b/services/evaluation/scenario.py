"""One actual local-server release morning with labelled simulated human approvals."""
from datetime import datetime
import json
from pathlib import Path
from time import perf_counter
from services.evaluation.runner import ROOT, prepare, execute, verify
from services.heartbeat import release_job, brief_job
from services.agent.run import save


def run(root=ROOT, mode='replay', token=None, provider=None):
    root = Path(root)
    bundle = root / 'evals/recordings/release-morning-v3'
    task = {'task_id': 'release-morning', 'category': 'scenario', 'mandate': 'mandate_a',
            'prompt': "Prepare this month's client credit note for the active mandate using the new release. Draft it to the client's CIO, request approval and send to the mock outbox only if the fixture human approves. Then prepare an evidence-backed watchlist entry for Hotel, request its own approval, and write only the approved entry. Finish with the actual completion results.",
            'expect': [], 'forbid': []}
    if mode == 'record':
        m = prepare(root, bundle, task, token, {'approve': ['send_email', 'watchlist_write']},
                    now=datetime.fromisoformat('2026-10-15T07:32:00-04:00'))
        m['budget']['max_steps_per_task'] = 12
        save(bundle / 'manifest.json', m)
        output = root / m['scratch'] / 'heartbeat'
        steps_file = bundle / 'workflow.json'
        if not steps_file.exists():
            started = perf_counter()
            release = release_job(root, output, datetime.fromisoformat('2026-10-15T06:00:00-04:00'))
            brief = brief_job(root, output, datetime.fromisoformat('2026-10-15T07:30:00-04:00'))
            steps = [{'step': 'release_tick_and_signals', 'ts': '2026-10-15T06:00:00-04:00', 'result': release},
                     {'step': 'deliver_morning_briefs', 'ts': '2026-10-15T07:30:00-04:00', 'result': brief}]
            save(steps_file, {'steps': steps, 'measured_workflow_seconds': perf_counter()-started})
        execute(root, bundle, 'record', provider)
    result = verify(root, bundle)
    m = json.loads((bundle / 'manifest.json').read_text())
    journal = json.loads((bundle / 'journal.json').read_text())
    sends = [e['result']['data'] for e in journal if e['name'] == 'send_email' and e['result'].get('ok')]
    writes = [e['result']['data'] for e in journal if e['name'] == 'watchlist_write' and e['result'].get('ok')]
    if not sends or not writes:
        raise RuntimeError('Scenario did not complete both the approved send and watchlist write; recording retained')
    wf = json.loads((bundle / 'workflow.json').read_text())
    outbox = root / m['scratch'] / 'outbox' / (sends[-1]['outbox_message_id'] + '.json')
    watchlist = root / m['scratch'] / 'agent/mandates/mandate_a/tool_state/watchlist/entries.json'
    if mode == 'record':
        assert outbox.is_file()
        assert any(e['watchlist_entry_id'] == writes[-1]['watchlist_entry_id'] for e in json.loads(watchlist.read_text()))
        # Copy the real local outbox artifact into the canonical (ignored) mock outbox.
        save(root / 'outputs/outbox' / outbox.name, json.loads(outbox.read_text()))
        save(bundle / 'server_artifacts.json', {'outbox': json.loads(outbox.read_text()),
            'watchlist_entry': next(e for e in json.loads(watchlist.read_text()) if e['watchlist_entry_id'] == writes[-1]['watchlist_entry_id'])})
    artifacts = json.loads((bundle / 'server_artifacts.json').read_text())
    if artifacts['outbox']['message_id'] != sends[-1]['outbox_message_id']:
        raise RuntimeError('Stored outbox receipt differs from recorded server result')
    if artifacts['watchlist_entry']['watchlist_entry_id'] != writes[-1]['watchlist_entry_id']:
        raise RuntimeError('Stored watchlist receipt differs from the recorded server result')
    scenario = {'provenance': 'openai-live', 'mandate': 'mandate_a',
        'approval_mode': 'explicit simulated fixture human; no real email sent',
        'outbox_message_id': sends[-1]['outbox_message_id'], 'watchlist_entry_id': writes[-1]['watchlist_entry_id'],
        'steps': wf['steps'] + [{'step': 'agent_and_server_actions', 'ts': m['clock'], 'actions': result['actions']}],
        'final_response': result['final_response'], 'estimated_model_usd': sum(e['usd'] for e in result['model_calls']),
        'model_calls': len(result['model_calls']), 'recorded_process_seconds': json.loads((bundle / 'timing.json').read_text())['wall_seconds'],
        'workflow_process_seconds': wf['measured_workflow_seconds'],
        'simulated_detection_to_brief_seconds': 5400,
        'publication_to_delivery_seconds': None,
        'latency_note': 'Recorded-feed fixture clock; publication time unavailable. Process time is measured separately.',
        'outbox_path': str((root / 'outputs/outbox' / outbox.name).relative_to(root)),
        'watchlist_path': str(watchlist.relative_to(root)),
        'durable_server_artifacts': str((bundle / 'server_artifacts.json').relative_to(root))}
    save(root / 'outputs/scenario/release_morning.json', scenario)
    return scenario
