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
