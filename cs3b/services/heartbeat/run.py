"""Run a workflow or a seven-day recorded-feed demonstration; no network/model calls."""
import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from time import perf_counter
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import pandas as pd
import yaml
from creditwatch import clock, evals, panel, signals
from services.signals.pairing import pair
from services.heartbeat.jobs import release_job, edgar_job, brief_job, hygiene_job, write
from tools.make_fixture import build


def pairing_report(root, reports, real_panel=None):
    settings = yaml.safe_load((root / 'params.yaml').read_text())
    materiality = settings['heartbeat']['materiality']
    results = {}
    for seed in range(4):
        rows, truth = build(seed)
        data = pd.DataFrame(rows)
        for col in panel.NUMERIC:
            if col in data:
                data[col] = pd.to_numeric(data[col], errors='coerce')
        results['fixture' if seed == 0 else f'variant_{seed}'] = evals.signal_scores(
            signals.find_signals(data, materiality, pair=pair), pd.DataFrame(truth).astype(str))
    data = panel.load_panel(root / settings['data']['panel'])
    coverage = signals.pairing_report(data, pair(data)).to_dict('records')
    results['coverage'] = coverage
    results['real_panel_review'] = 'pending: no real panel supplied'
    if real_panel:
        real = panel.load_panel(real_panel)
        problems = panel.validate(real)
        if problems:
            raise ValueError('; '.join(problems))
        sample = pair(real).head(20)[['adsh', 'identifier', 'identifier_prior', 'source_rows', 'source_rows_prior']].copy()
        sample['review_verdict'] = ''
        sample['review_notes'] = ''
        reports.mkdir(parents=True, exist_ok=True)
        sample.to_csv(reports / 'real_pairs_for_review.csv', index=False)
        results['real_panel_review'] = 'pending manual review: real_pairs_for_review.csv'
    write(reports / 'pairing.json', json.dumps(results, indent=2) + '\n')
    return results


def metrics(output, start, end):
    with sqlite3.connect(output / 'state.sqlite') as db:
        events = [(json.loads(p), s) for p, s in db.execute('SELECT payload,status FROM events')]
        runs = list(db.execute('SELECT job,ts,elapsed,new_events FROM runs'))
    weeks = (end - start).total_seconds() / (7 * 86400)
    delivered = [p for p, s in events if s == 'delivered']
    scopes = sorted({p['mandate'] for p, _ in events})
    latency = [(datetime.fromisoformat(p['delivered_at']) - datetime.fromisoformat(p['detected_at'])).total_seconds() for p in delivered]
    idle = [r for r in runs if r[3] == 0]
    return dict(observation_start=start.isoformat(), observation_end=end.isoformat(), observation_weeks=weeks,
        mode='seven-day simulation with recorded fixture feeds; not live delivery or an infrastructure cost estimate',
        delivered_alerts=len(delivered), held_remaining=sum(s == 'held' for _, s in events),
        alerts_per_mandate_week={m: sum(p['mandate'] == m for p in delivered)/weeks for m in scopes},
        detection_to_delivery_seconds={'max': max(latency, default=0), 'mean': sum(latency)/len(latency) if latency else 0},
        publication_to_detection_seconds=None,
        publication_latency_note='Release publication timestamp unavailable; recorded EDGAR notices are historical backfill, not live latency.',
        job_runs=len(runs), idle_runs=len(idle), measured_idle_job_seconds=sum(r[2] for r in idle),
        timing_note='Python workflow duration through transaction preparation; excludes export, scheduler and network overhead.',
        model_calls=0, model_api_cost_usd=0, infrastructure_cost_usd=None)


def demo(root=ROOT, output=None, reports=None, start=None):
    root = Path(root)
    output = Path(output) if output else root / 'outputs/heartbeat'
    reports = Path(reports) if reports else root / 'reports/heartbeat'
    start = (start or clock.clock()).replace(hour=0, minute=0, second=0, microsecond=0)
    # An existing state is deliberately retained. To repeat the measured experiment,
    # choose a NEW output directory; never silently erase delivered work.
    if (output / 'state.sqlite').exists():
        raise ValueError('Demo requires a fresh --output directory; existing state is preserved')
    end = start + timedelta(days=7)
    for day in range(7):
        date = start + timedelta(days=day)
        for half_hour in range(48):
            now = date + timedelta(minutes=30*half_hour)
            if now.hour == 6 and now.minute == 0:
                release_job(root, output, now)
            edgar_job(root, output, now)
            if now.hour == 7 and now.minute == 30:
                brief_job(root, output, now)
            if now.weekday() == 0 and now.hour == 8 and now.minute == 0:
                hygiene_job(root, output, now)
    report = metrics(output, start, end)
    write(reports / 'metrics.json', json.dumps(report, indent=2) + '\n')
    pairing_report(root, reports)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', choices=['release', 'edgar', 'brief', 'hygiene', 'demo', 'pairing'])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--reports', type=Path, default=ROOT / 'reports/heartbeat')
    parser.add_argument('--now', help='Timezone-aware ISO time; default LANTERN_CLOCK')
    parser.add_argument('--real-panel', type=Path)
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now) if args.now else clock.clock()
    if args.job == 'demo':
        result = demo(output=args.output, reports=args.reports, start=now)
    elif args.job == 'pairing':
        result = pairing_report(ROOT, args.reports, args.real_panel)
    else:
        result = {'release': release_job, 'edgar': edgar_job, 'brief': brief_job, 'hygiene': hygiene_job}[args.job](output=args.output, now=now)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
