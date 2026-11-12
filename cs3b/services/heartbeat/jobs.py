"""Local delivery to Priya, not external email. SQLite transactions make retries safe."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
from time import perf_counter
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
import yaml
from creditwatch import clock, heartbeat, panel, policy, signals
from services.signals.pairing import pair


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(path)


def key(*values):
    return hashlib.sha256('|'.join(map(str, values)).encode()).hexdigest()[:24]


class Engine:
    def __init__(self, root=ROOT, output=None, now=None):
        self.root = Path(root)
        self.p = yaml.safe_load((self.root / 'params.yaml').read_text())
        self.now = now or clock.clock()
        if self.now.tzinfo is None:
            raise ValueError('Use a timezone-aware clock')
        self.now = self.now.astimezone(ZoneInfo(self.p['heartbeat']['timezone']))
        self.fx = self.root / self.p['data']['fixture_dir']
        self.mandates = json.loads((self.root / self.p['data']['mandates']).read_text())
        self.registry = json.loads((self.root / self.p['data']['registry']).read_text())
        self.canaries = json.loads((self.fx / 'canaries.json').read_text())
        self.out = Path(output) if output else self.root / 'outputs/heartbeat'
        self.out.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.out / 'state.sqlite', timeout=30)
        try:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, payload TEXT, status TEXT);
            CREATE TABLE IF NOT EXISTS briefs (id TEXT PRIMARY KEY, payload TEXT);
            CREATE TABLE IF NOT EXISTS runs (job TEXT, ts TEXT, elapsed REAL, new_events INTEGER);
            ''')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
            # Serialize exports under the same database lock as competing jobs.
            db.execute('BEGIN IMMEDIATE')
            self.export(db)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def quiet(self):
        q = self.p['heartbeat']['quiet_hours']
        start, end, hour = q['start'], q['end'], self.now.hour
        return (hour >= start or hour < end) if start > end else start <= hour < end

    def private_check(self, text, mandate):
        forbidden = policy.confidential_terms(self.mandates, mandate)
        terms = forbidden['terms'] + [c for m, cs in self.canaries.items() if m != mandate for c in cs]
        if policy.mentions(text, forbidden['names']) or policy.leaks(text, terms):
            raise ValueError('Cross-mandate content blocked')

    def add(self, db, mandate, bdc, trigger, rule, text, citations, **extra):
        eid = key(mandate, trigger, rule)
        held = bdc in self.mandates[mandate]['positions']
        status = ('held' if self.quiet() else 'delivered') if held else 'not_material'
        event = dict(alert_id=eid, ts=self.now.isoformat(), mandate=mandate, bdc=bdc,
                     trigger=trigger, rule=rule, text=text, citations=citations,
                     detected_at=self.now.isoformat(), delivered_at=self.now.isoformat() if status == 'delivered' else None,
                     recipient='priya', delivery_channel='local_inbox', **extra)
        self.private_check(json.dumps(event, ensure_ascii=False), mandate)
        return db.execute('INSERT OR IGNORE INTO events VALUES (?,?,?)',
                          (eid, json.dumps(event), status)).rowcount

    def run(self, job, action):
        started = perf_counter()
        with self.transaction() as db:
            count = action(db)
            elapsed = perf_counter() - started
            db.execute('INSERT INTO runs VALUES (?,?,?,?)', (job, self.now.isoformat(), elapsed, count))
        return {'job': job, 'new_events': count, 'elapsed_seconds': elapsed}

    def export(self, db):
        events = [{**json.loads(p), 'status': s} for p, s in db.execute('SELECT payload,status FROM events ORDER BY id')]
        alerts = [e for e in events if e['status'] == 'delivered']
        write(self.out / 'alerts.jsonl', ''.join(json.dumps(e, sort_keys=True) + '\n' for e in alerts))
        write(self.out / 'decisions.jsonl', ''.join(json.dumps(e, sort_keys=True) + '\n' for e in events))
        for m in self.mandates:
            own = [e for e in alerts if e['mandate'] == m]
            write(self.out / 'inbox' / m / 'alerts.jsonl', ''.join(json.dumps(e, sort_keys=True) + '\n' for e in own))
        for payload, in db.execute('SELECT payload FROM briefs ORDER BY id'):
            brief = json.loads(payload)
            write(self.out / 'inbox' / brief['mandate'] / (brief['brief_id'] + '.json'), json.dumps(brief, indent=2) + '\n')

    def recorded_only(self):
        if not self.p['data']['use_fixture']:
            raise ValueError('Live refresh is not configured: supply a release HEAD/panel refresh or EDGAR feed adapter')


def release_job(root=ROOT, output=None, now=None, head=None, refresh=None):
    e = Engine(root, output, now)
    if head is None or refresh is None:
        e.recorded_only()
    feed = json.loads((e.fx / 'release_heads.json').read_text())
    def action(db):
        row = db.execute("SELECT value FROM kv WHERE key='last_release'").fetchone()
        last = row[0] if row else feed['last_seen']
        tick = heartbeat.release_tick(last, head or (lambda url: feed['heads'].get(url, 404)), e.p['sec']['base_url'])
        if not tick['published']:
            return 0
        # Fixture snapshot stands in for the upstream CS2B refresh. Live mode must inject it.
        data = refresh(tick['release']) if refresh else panel.load_panel(e.root / e.p['data']['panel'])
        problems = panel.validate(data) + panel.check_mandates(e.mandates, data)
        if problems:
            raise ValueError('; '.join(problems))
        paired = pair(data)
        coverage = {r['adsh']: r for r in signals.pairing_report(data, paired).to_dict('records')}
        found = signals.find_signals(data, e.p['heartbeat']['materiality'], pair=pair)
        count = 0
        for s in found.to_dict('records'):
            for m, mandate in e.mandates.items():
                if s['name'] not in mandate['positions']:
                    continue
                text = f"{s['rule']}: {s['identifier']}; before {s['before']}, after {s['after']}."
                count += e.add(db, m, s['name'], f"{s['adsh']}#{s['row']}", s['rule'], text,
                               [f"{s['adsh']}#{s['row']}", f"{s['adsh']}#{s['prior_row']}"],
                               release=tick['release'], coverage=coverage[s['adsh']])
        db.execute("INSERT OR REPLACE INTO kv VALUES ('last_release', ?)", (tick['release'],))
        db.execute('INSERT OR REPLACE INTO kv VALUES (?,?)', ('release:' + tick['release'], e.now.isoformat()))
        return count
    return e.run('release', action)


def edgar_job(root=ROOT, output=None, now=None, feed=None):
    e = Engine(root, output, now)
    if feed is None:
        e.recorded_only()
        feed = json.loads((e.fx / 'edgar_recent.json').read_text())
    def action(db):
        count = 0
        for bdc, cik in e.registry['bdc_cik'].items():
            recent = feed.get(cik, {'form': [], 'items': [], 'accessionNumber': [], 'acceptanceDateTime': []})
            for f in heartbeat.new_filings(recent, set()):
                accepted = datetime.fromisoformat(f['accepted'].replace('Z', '+00:00'))
                if accepted > e.now:
                    continue
                for m in e.mandates:
                    count += e.add(db, m, bdc, f['accn'], 'FILING',
                                   f"New {f['form']} filing for {bdc}.", [f['accn']],
                                   accepted_at=accepted.isoformat(), form=f['form'])
        return count
    return e.run('edgar', action)


def brief_job(root=ROOT, output=None, now=None):
    e = Engine(root, output, now)
    def action(db):
        if e.now.weekday() >= 5 or e.quiet() or (e.now.hour, e.now.minute) < (7, 30):
            return 0
        releases = [k.split(':', 1)[1] for k, in db.execute("SELECT key FROM kv WHERE key LIKE 'release:%'")]
        count = 0
        for m in e.mandates:
            events = [(i, json.loads(p), s) for i, p, s in db.execute('SELECT id,payload,status FROM events ORDER BY id') if json.loads(p)['mandate'] == m]
            # A release brief is sent once per mandate/release. Pending filing notices
            # also receive a morning digest even on days without a new release.
            groups = releases + ['filings:' + e.now.date().isoformat()]
            for group in groups:
                bid = 'brief-' + key(m, group)
                if db.execute('SELECT 1 FROM briefs WHERE id=?', (bid,)).fetchone():
                    continue
                selected = [(i, p, s) for i, p, s in events if s != 'not_material' and
                            (p.get('release') == group if not group.startswith('filings:') else s == 'held' and 'release' not in p)]
                if group.startswith('filings:') and not selected:
                    continue
                brief = dict(brief_id=bid, mandate=m, recipient='priya', ts=e.now.isoformat(), release=group,
                             text='Morning brief: ' + str(len(selected)) + ' relevant items.',
                             items=[p for _, p, _ in selected], delivery_channel='local_inbox')
                e.private_check(json.dumps(brief, ensure_ascii=False), m)
                db.execute('INSERT INTO briefs VALUES (?,?)', (bid, json.dumps(brief)))
                for i, p, status in selected:
                    if status == 'held':
                        p['delivered_at'] = e.now.isoformat()
                        db.execute("UPDATE events SET payload=?,status='delivered' WHERE id=?", (json.dumps(p), i))
                count += 1
        return count
    return e.run('brief', action)


def hygiene_job(root=ROOT, output=None, now=None):
    e = Engine(root, output, now)
    cfg = e.p['heartbeat'].get('hygiene', {})
    def action(db):
        if e.now.weekday() != 0 or e.now.hour < 8:
            return 0
        count = 0
        week = e.now.strftime('%G-W%V')
        for m, mandate in e.mandates.items():
            notes = []
            watch_items = list(mandate.get('watchlist', []))
            managed = e.root / e.p['agent']['workspace'] / 'mandates' / m / 'tool_state/watchlist/entries.json'
            if managed.exists():
                watch_items.extend(json.loads(managed.read_text()))
            for item in watch_items:
                day = item.get('last_reviewed', item.get('added'))
                if not day:
                    notes.append({'kind': 'watchlist_review_date_missing', 'bdc': item['bdc']})
                if day and (e.now.date() - datetime.fromisoformat(day).date()).days >= cfg.get('stale_days', 30):
                    notes.append({'kind': 'stale_watchlist', 'bdc': item['bdc'], 'last_reviewed': day})
            # Explicit configured dates; never invent client reporting obligations.
            dates = list(cfg.get('reporting_dates', {}).get(m, []))
            ordinal = cfg.get('monthly_business_day', {}).get(m)
            if ordinal is not None:
                if not 1 <= ordinal <= 20:
                    raise ValueError('monthly_business_day must be between 1 and 20')
                month = e.now.date().replace(day=1)
                for _ in range(2):
                    day, n = month, 0
                    while True:
                        n += day.weekday() < 5
                        if n == ordinal:
                            dates.append(day.isoformat()); break
                        day += timedelta(days=1)
                    month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
            for date_text in sorted(set(dates)):
                due = datetime.fromisoformat(date_text).date()
                day, business_days = e.now.date(), 0
                while day < due:
                    day += timedelta(days=1)
                    business_days += day.weekday() < 5
                if due >= e.now.date() and business_days <= cfg.get('due_business_days', 5):
                    notes.append({'kind': 'reporting_due', 'date': date_text})
            bid = 'hygiene-' + key(m, week)
            payload = dict(brief_id=bid, mandate=m, recipient='priya', ts=e.now.isoformat(), items=notes,
                           text='Review reminders; no watchlist changes made.', delivery_channel='local_inbox',
                           reporting_schedule_configured=bool(dates))
            e.private_check(json.dumps(payload, ensure_ascii=False), m)
            count += db.execute('INSERT OR IGNORE INTO briefs VALUES (?,?)', (bid, json.dumps(payload))).rowcount
        return count
    return e.run('hygiene', action)
