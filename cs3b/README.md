# Lab 3B starter kit: Credit Watch

Building blocks and notebooks for **Project LANTERN, Tool Tutorial Part 3B** and **Case Study 3B**: a
credit-watch agent that watches two clients' BDC holdings, explains each SEC release with the rows that
prove it, keeps the clients apart, and acts only with approval.

The kit gives you tested building blocks, not a solution. Your tool server, agent, DAGs, eval runner and
reports are the case study.

## Setup (10 minutes)
Copy this folder into your team repository as `cs3b/` (next to `cs2b/`), and run everything from inside it.
```
cd cs3b
python -m venv .venv && source .venv/bin/activate      # Python 3.10 or later
pip install -r requirements.txt
jupyter lab                                             # open notebooks/00_setup.ipynb
```
Notebook 00 copies `agent_seed/` to `agent/`. Edit `agent/`, never the seed.

## What is here
- `notebooks/`: 00 (setup) and 23 to 31, one per lab of Tool Tutorial Part 3B.
- `src/creditwatch/`: clock, workspace, channel, catalog, loop, llm (record/replay), skills, memory,
  panel, signals, heartbeat, approvals, policy, audit, evals, econ, a deterministic stand-in model, and
  `check` (the Case Study 3B self-check).
- `agent_seed/`: the seed workspace (SOUL, AGENTS, PRINCIPAL, HEARTBEAT, two mandates, two skills, a lockfile).
- `data/fixture/`: four fictional BDCs (a two-period panel with planted, registered events), two fictional
  client mandates, a registry, an inbox, scripted corrections, recorded EDGAR and release feeds, a dev task suite.
- `dags/release_watch_dag.py`: one example DAG, a thin wrapper over importable functions.
- `tests/`: `python tests/run_tests.py` (or `pytest -q`).
- `tools/`: `run_notebooks.py` (every notebook, in order), `make_fixture.py [--seed N]` (the fixture, or a
  structural variant), `export_panel_from_lab2b.py` (a two-period panel from the Lab 2B baseline).

## Commands
```
python tests/run_tests.py                     # the kit's tests
python tools/run_notebooks.py                 # every notebook, offline
PYTHONPATH=src python -m creditwatch.check    # Case Study 3B self-check on your deliverables
python tools/make_fixture.py --seed 7 --out /tmp/variant7    # a variant, to test your pairing
```

## Switching to your real panel (Case Study 3B, Section 4)
1. Export both schedules of every admitted filing from your Case Study 2B work:
   `python tools/export_panel_from_lab2b.py ../cs2b data/panel_2p.parquet`
   (or write your own export with `creditwatch.panel.from_holdings`, and check it with `panel.validate`).
2. Copy `data/fixture/mandates.json` and `registry.json` to `data/real/`, point each mandate's positions
   at BDCs in your panel **by their exact SUB names**, and keep every client, contact and address fictional
   (`.example` domains only).
3. In `params.yaml`, set `data.panel`, `data.mandates` and `data.registry` to the new files, and
   `data.use_fixture: false`.
4. `creditwatch.panel.check_mandates` must return `[]`: a misspelled BDC name routes nothing, silently.

## Rules that never bend
- The agent sends only to the mock outbox (`outputs/outbox/`) and writes only to its own workspace. No real email, ever.
- Every client, contact and person is fictional. Never invent an event, mark or status about a real company.
- Repositories stay private until grades are returned.


## Lab 28: heartbeat workflows

Run from `cs3b/` with `.venv311` activated. The implementation delivers to a
local inbox for Priya, separately for each mandate; it never sends client email.

```bash
python -m services.heartbeat.run release
python -m services.heartbeat.run edgar
python -m services.heartbeat.run brief --now 2026-10-15T07:30:00-04:00
python -m services.heartbeat.run hygiene --now 2026-10-19T08:00:00-04:00
python -m pytest tests/test_heartbeat_workflows.py -q
```

All commands accept `--output` to isolate a demonstration from existing state.
The injected default clock is the lab clock. Scheduled DAGs use Airflow's interval
end, with America/New_York schedules. They are defined but not automatically
activated by running the notebook. Each thin DAG runs one atomic workflow task:
release check → panel refresh → pairing → signal detection → routing/delivery;
EDGAR filtering → relevance decisions → routing/delivery; pending items → per-client
briefs → delivered status; or watchlist/reporting review → reminders.

Schedules: release daily 06:00; EDGAR every 30 minutes; brief weekdays 07:30;
hygiene Mondays 08:00. A release gets one brief per mandate; held filing notices
also receive a morning digest without requiring another release. Weekend holds
are retained until a weekday brief. Quiet hours come from `params.yaml`.
Airflow definitions use the [official Task SDK](https://airflow.apache.org/docs/task-sdk/stable/api.html).
To deploy, install Airflow 3 in its own environment/container, make this project's
`services`, `src`, configuration, data and writable output directory available to
all workers, and add these four files to its DAG folder. No background scheduler
or live SEC refresh has been started by this lab implementation.

`outputs/heartbeat/state.sqlite` keeps decisions, held items, release progress,
briefs and run timings across restarts. Transactions and unique event IDs prevent
duplicate delivery on retries. JSON/JSONL files are regenerable local delivery
projections; a retry repairs exports if interrupted after the database commit.
Keep the state database for ongoing use (it is ignored by Git). Independent
workers must share the same output/state storage. This local SQLite workflow is
not a distributed external-email delivery system.

Outputs:
- `outputs/heartbeat/alerts.jsonl`: delivered alerts with routing and citations.
- `outputs/heartbeat/decisions.jsonl`: includes held and not-material decisions.
- `outputs/heartbeat/inbox/<mandate>/`: local alerts, release/filing briefs and reminders.
- `reports/heartbeat/pairing.json`: fixture/variant precision, recall and coverage.
- `reports/heartbeat/metrics.json`: measured seven-day fixture simulation.

To repeat the experiment, use a fresh output directory; the demo refuses to erase state:

```bash
python -m services.heartbeat.run demo --output /tmp/lab28-demo-new --reports /tmp/lab28-report-new
```

The measured model/API cost is zero because these checks are deterministic.
Measured Python processing time is reported separately from unmeasured hosting
cost. Detection-to-delivery latency includes quiet-hour holds. Real publication
latency is not claimed: release publication timestamps are absent and EDGAR
fixtures are historical backfill. Alerts per mandate-week use a full simulated
seven-day observation window, not a production traffic estimate.

Pairing strips standalone rate and maturity segments but keeps borrower/tranche
identity and requires a unique pair within the same accession, CIK and investment
type. Ambiguity is left unpaired, never resolved by a many-to-many join. The MCP
`bdc_signals` tool uses this matcher too. This conservative parser is validated on
the supplied formats; real identifiers still require review.

```bash
python -m services.heartbeat.run pairing --real-panel /absolute/path/to/panel_2p.parquet
```

This writes a real-pair review CSV with both identifiers and row references.
Review the source filing rows and record verdicts/notes; generation alone does not
constitute hand-checking. No real panel was available during implementation, so
that requirement is explicitly pending. Live jobs require injected release HEAD,
CS2B panel-refresh and EDGAR-feed adapters; fixture mode uses the saved snapshots.

Hygiene checks configured watchlist dates and managed entries; missing review
dates are reported rather than guessed. Mandate A's tenth-business-day monthly
rule is configured in `params.yaml`; business days mean Monday–Friday in this lab,
without a holiday calendar. Add explicit quarterly dates under
`heartbeat.hygiene.reporting_dates`; unspecified dates are not invented. Hygiene
only reminds Priya—it does not mutate a watchlist or send an email.
