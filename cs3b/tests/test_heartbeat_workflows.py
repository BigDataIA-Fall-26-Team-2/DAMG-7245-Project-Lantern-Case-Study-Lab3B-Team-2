"""Lab 28 acceptance: matching, routing, restarts, quiet-hours delivery and measurements."""
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import types

import pandas as pd
import pytest
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from creditwatch import evals, panel, policy
from services.signals.pairing import pair
from services.heartbeat.jobs import Engine, release_job, edgar_job, brief_job, hygiene_job
from services.heartbeat.run import pairing_report, metrics
from tools.make_fixture import build
from creditwatch import signals

NOW = datetime.fromisoformat('2026-10-15T06:00:00-04:00')
M = {'markdown_points': 5, 'pik_points': .5, 'extension_months': 6}


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.mark.parametrize('seed', [0, 1, 2, 3, 17, 43])
def test_pairing_detects_every_planted_event_without_false_positives(seed):
    rows, truth = build(seed)
    data = pd.DataFrame(rows)
    for col in panel.NUMERIC:
        if col in data: data[col] = pd.to_numeric(data[col], errors='coerce')
    paired = pair(data)
    found = signals.find_signals(data, M, pair=pair)
    score = evals.signal_scores(found, pd.DataFrame(truth).astype(str))
    assert score['precision'] == score['recall'] == 1
    assert len(found) == 9
    assert not paired.duplicated(['adsh', 'source_rows']).any()
    assert not paired.duplicated(['adsh', 'source_rows_prior']).any()
    expected = {(t['adsh'], t['row']): t['prior_row'] for t in truth}
    for s in found.to_dict('records'):
        assert s['prior_row'] == expected[s['adsh'], s['row']]


def test_pairing_abstains_on_ambiguity_and_never_crosses_filings():
    data = panel.load_panel(ROOT / 'data/fixture/panel_2p.csv')
    loan = data[(data.period_role == 'current') & data.identifier.str.contains('Cedar Ridge')].iloc[[0]].copy()
    loan['identifier'] = loan.identifier.str.replace('9.80%', '8.80%', regex=False)
    loan['source_rows'] = '999'
    result = pair(pd.concat([data, loan]))
    assert not result.identifier.str.contains('Cedar Ridge').any()
    data.loc[data.period_role == 'prior', 'adsh'] = 'different-filing'
    assert pair(data).empty


def test_release_hold_survives_restart_delivers_once_with_evidence(tmp_path):
    output = tmp_path / 'heartbeat'
    first = release_job(output=output, now=NOW)
    assert first['new_events'] == 12  # A's 8 + B's 4, including shared Hotel signals.
    assert records(output / 'alerts.jsonl') == []
    pending = records(output / 'decisions.jsonl')
    assert all(e['status'] == 'held' and len(e['citations']) == 2 for e in pending)
    assert release_job(output=output, now=NOW)['new_events'] == 0
    assert brief_job(output=output, now=NOW.replace(hour=7, minute=29))['new_events'] == 0
    assert brief_job(output=output, now=NOW.replace(hour=7, minute=30))['new_events'] == 2
    alerts = records(output / 'alerts.jsonl')
    assert len(alerts) == 12 and len({a['alert_id'] for a in alerts}) == 12
    assert brief_job(output=output, now=NOW.replace(hour=9))['new_events'] == 0
    assert records(output / 'alerts.jsonl') == alerts
    mandates = json.loads((ROOT / 'data/fixture/mandates.json').read_text())
    canaries = json.loads((ROOT / 'data/fixture/canaries.json').read_text())
    for m in mandates:
        for f in (output / 'inbox' / m).glob('*'):
            text = f.read_text()
            forbidden = policy.confidential_terms(mandates, m)
            assert not policy.mentions(text, forbidden['names'])
            assert not policy.leaks(text, forbidden['terms'] + [c for other, cs in canaries.items() if other != m for c in cs])
    for a in alerts:
        assert a['bdc'] in mandates[a['mandate']]['positions']
        assert a['coverage']['paired'] <= a['coverage']['debt_holdings']
    report = metrics(output, NOW, NOW + timedelta(days=7))
    assert report['alerts_per_mandate_week'] == {'mandate_a': 8, 'mandate_b': 4}
    assert report['detection_to_delivery_seconds']['max'] == 5400
    assert report['model_api_cost_usd'] == 0 and report['infrastructure_cost_usd'] is None


def test_refresh_failure_does_not_advance_release(tmp_path):
    def fail(release): raise RuntimeError('upstream unavailable')
    with pytest.raises(RuntimeError):
        release_job(output=tmp_path, now=NOW, refresh=fail)
    assert release_job(output=tmp_path, now=NOW)['new_events'] == 12


def test_edgar_filters_routes_and_retries(tmp_path):
    assert edgar_job(output=tmp_path, now=NOW.replace(hour=9))['new_events'] == 8
    delivered = records(tmp_path / 'alerts.jsonl')
    decisions = records(tmp_path / 'decisions.jsonl')
    assert len(delivered) == 4 and sum(e['status'] == 'not_material' for e in decisions) == 4
    assert all(not e['trigger'].endswith('000110') for e in decisions)  # unrelated 8-K
    assert edgar_job(output=tmp_path, now=NOW.replace(hour=10))['new_events'] == 0
    assert records(tmp_path / 'alerts.jsonl') == delivered


def test_weekend_hold_and_new_filing_digest_without_release(tmp_path):
    saturday = NOW.replace(day=17)
    edgar_job(output=tmp_path, now=saturday)
    assert brief_job(output=tmp_path, now=saturday.replace(hour=8))['new_events'] == 0
    assert brief_job(output=tmp_path, now=saturday.replace(day=19, hour=7, minute=30))['new_events'] == 2
    assert len(records(tmp_path / 'alerts.jsonl')) == 4


def test_hygiene_configured_dates_and_weekly_dedup(tmp_path):
    import yaml
    root = tmp_path / 'root'; root.mkdir()
    p = yaml.safe_load((ROOT / 'params.yaml').read_text())
    p['heartbeat']['hygiene'] = {'stale_days': 30, 'due_business_days': 5,
                                'reporting_dates': {'mandate_a': ['2026-10-23', '2026-11-30']}}
    (root / 'params.yaml').write_text(yaml.safe_dump(p))
    (root / 'data').symlink_to(ROOT / 'data', target_is_directory=True)
    output = tmp_path / 'output'
    assert hygiene_job(root, output, NOW.replace(day=19, hour=8))['new_events'] == 2
    files = list((output / 'inbox/mandate_a').glob('hygiene*'))
    report = json.loads(files[0].read_text())
    assert {i['kind'] for i in report['items']} == {'stale_watchlist', 'reporting_due'}
    assert len(report['items']) == 2
    assert hygiene_job(root, output, NOW.replace(day=19, hour=9))['new_events'] == 0


def test_release_change_only_creates_new_signal_ids_once(tmp_path):
    release_job(output=tmp_path, now=NOW)
    # Another published release with the same filing rows must not alert twice.
    assert release_job(output=tmp_path, now=NOW, head=lambda _: 200)['new_events'] == 0
    assert len(records(tmp_path / 'decisions.jsonl')) == 12


def test_dag_definitions_register_schedules_without_running_jobs(monkeypatch):
    # Validate declaration/wiring offline. This is NOT an Airflow scheduler test.
    registered = []
    sdk = types.ModuleType('airflow.sdk')
    def dag(**options):
        registered.append(options)
        return lambda fn: fn
    sdk.dag = dag
    sdk.task = lambda fn: lambda: None
    sdk.get_current_context = lambda: {'data_interval_end': NOW}
    monkeypatch.setitem(sys.modules, 'airflow', types.ModuleType('airflow'))
    monkeypatch.setitem(sys.modules, 'airflow.sdk', sdk)
    pendulum = types.ModuleType('pendulum'); pendulum.datetime = lambda *a, **k: NOW
    monkeypatch.setitem(sys.modules, 'pendulum', pendulum)
    for file in sorted((ROOT / 'dags').glob('*_dag.py')):
        spec = importlib.util.spec_from_file_location(file.stem, file)
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    assert {r['dag_id']: r['schedule'] for r in registered} == {
        'release_watch_dag': '0 6 * * *', 'edgar_watch_dag': '*/30 * * * *',
        'monthly_brief_dag': '30 7 * * 1-5', 'hygiene_dag': '0 8 * * 1'}
    assert all(not r['catchup'] for r in registered)


def test_monthly_business_day_reminder_from_mandate_terms(tmp_path):
    now = NOW.replace(day=12, hour=8)
    hygiene_job(output=tmp_path, now=now)
    report = json.loads(next((tmp_path / 'inbox/mandate_a').glob('hygiene*')).read_text())
    assert {'kind': 'reporting_due', 'date': '2026-10-14'} in report['items']
