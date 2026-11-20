# Lab 4B starter kit: Ask the Panel

Building blocks and notebooks for **Project LANTERN, Tool Tutorial Part 4B**: a natural-language
query interface over the BDC panel. An analyst types a question; a LangGraph agent writes one SQL
query as a Pydantic object, runs it through your MCP query server, and answers with the rows and
the SQL behind them.

The kit gives you tested building blocks, not a solution. Your view, contract, server, agent, app,
ten questions and demo are the lab. **Due Friday 20 November 2026, 3:59 p.m. ET.**

## Setup (10 minutes)
Copy this folder into your team repository as `cs4b/` (next to `cs3b/`), and run every command from
inside it.
```
cd cs4b
python -m venv .venv && source .venv/bin/activate      # Python 3.11 or later
pip install -r requirements.txt
python tests/run_tests.py                               # 26/26 kit tests
python tools/run_notebooks.py                           # 6/6 notebooks, offline
jupyter lab                                             # start with notebooks/00_setup.ipynb
```
Record mode needs a Gemini API key (free, from Google AI Studio): `export GEMINI_API_KEY=...`.
Replay, the tests and grading need no key. Never commit it.

## What is here
- `notebooks/`: 00 (setup) and 32 to 36, one per lab of Tool Tutorial Part 4B. They run offline on the
  fixture with a stand-in model.
- `src/askpanel/`: `db` (panel to SQLite, the view contract and its check), `gate` (read-only connection,
  authorizer, static check, row cap, timeout), `catalog` (the four-tool catalog), `tools` (plain versions
  of the four tools, and the column descriptions the model reads), `nodes` (the agent's five nodes and two
  routers, plus `run_plain`, which runs the same graph without LangGraph), `llm` (record/replay, as in
  Lab 3B), `audit`, `clock`, `standin` (a deterministic stand-in model), `questions` (coverage rules),
  `econ`, and `check` (the self-check).
- `data/fixture/panel_2p.csv`: the Lab 3B fixture panel, four fictional BDCs with two schedules each.
- `data/real/`: put your Lab 3B real panel here as `panel_2p.parquet` (or `.csv`) and commit it.
- `questions/questions.example.yaml`, `outputs/economics.example.md`, `outputs/failures.example.md`:
  the formats. Copy each without `.example` and write your own.
- `agent/`, `services/mcp/`, `app/`, `sql/`: empty folders (with `__init__.py` where Python needs one)
  for your code.
- `tools/build_db.py`: builds the query database from a panel and your view. `tools/run_notebooks.py`.

## What you build
| File | Part | Lab |
|---|---|---|
| `sql/holdings_v.sql` | 0: the view | 32B |
| `agent/contract.py` | 1: `SchemaCatalog`, `QueryRequest`, `SQLQuery`, `QueryResult`, `validate_query` | 33B |
| `services/mcp/server.py`, `tests/test_server.py` | 2: the MCP query server and its tests | 34B |
| `agent/mcp_client.py` | 2: the synchronous client the agent and app use | 34B |
| `agent/model.py`, `agent/graph.py`, `agent/run.py` | 3: the model behind record/replay, the LangGraph agent, the runner | 35B |
| `app/streamlit_app.py` | 4: the interface | 36B |
| `questions/questions.yaml`, `outputs/questions/`, `outputs/cache/` | 5: ten questions, answered and replayable | 36B |
| `outputs/economics.md`, `outputs/failures.md` | 6: unit economics and the failure log | 36B |
| `README.md` (yours, at the top of `cs4b/`) | setup, architecture, an Inspector screenshot, the demo link | 36B |

Replace this README with your own when you submit; keep the setup commands.

## Building on the fixture, then on your real panel
1. Build everything on the fixture first (`data.use_real: false` in `params.yaml`).
2. Copy your Lab 3B real panel to `data/real/panel_2p.parquet` (or `.csv`; set `data.real_panel` if you
   use another name) and commit it.
3. Set `data.use_real: true` and run `python tools/build_db.py`: it rebuilds `data/panel.sqlite` from
   your real panel and checks the view on it.
4. Record your ten questions on the real panel (`python agent/run.py --mode record`), then replay them.

## Commands
```
python tests/run_tests.py                       # the kit's tests
python tools/run_notebooks.py                   # every notebook, offline
python tools/build_db.py                        # data/panel.sqlite from the panel params.yaml selects, plus your view
PYTHONPATH=src python -m askpanel.check         # the Lab 4B self-check (12 checks)
```

## Rules that never bend
- The agent and the app reach the data **only** through your MCP server. No `sqlite3` in `agent/` or `app/`.
- The server opens the database read-only, with the authorizer (`gate.connect_ro`).
- Commit `outputs/questions/` and `outputs/cache/`: graders replay your ten questions from them, free and
  offline. Never commit an API key.
- Public SEC data only; every client and person is fictional. Repositories stay private until grades are
  returned.
