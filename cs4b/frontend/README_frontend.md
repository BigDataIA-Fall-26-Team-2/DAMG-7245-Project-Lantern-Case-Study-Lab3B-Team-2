# Ask the Panel: web app (FastAPI + React)

A web front end for the Lab 4B agent. Nothing in `cs4b/` was changed. The work adds two folders:

```
cs4b/api/        FastAPI backend: reuses agent/graph.py, agent/model.py, agent/mcp_client.py
                 and services/mcp/server.py. It never opens the database.
cs4b/frontend/   React 18 + Vite 5 + TypeScript + Tailwind 3
```

```
browser :5173 ──/api/*──> Vite dev proxy ──> FastAPI :8000 ──> LangGraph agent (built once)
                                                 │                 │
                                                 │          PanelClient ── MCP (in memory) ──> services/mcp/server.py
                                                 │                                              └─ gate ─> SQLite (read-only)
                                                 └─ replay cache: outputs/cache/
```

## Prerequisites
- Python **3.12+**. The pinned `numpy==2.5.4` has no build for 3.11.
- Node.js 18+ (tested with 23.10) and npm.

## 1. Backend
Run every command from `cs4b/`:

```bash
cd cs4b
```

```bash
python3.12 -m venv .venv && source .venv/bin/activate
```

```bash
pip install -r requirements.txt -r api/requirements.txt
```

```bash
python tools/build_db.py
```

```bash
uvicorn api.main:app --port 8000
```

- Swagger UI: http://127.0.0.1:8000/docs. ReDoc: http://127.0.0.1:8000/redoc.
- Replay mode is the default. It needs no key, and only recorded questions answer.

### Live mode (optional)
The API always builds the replay graph. It also builds a live graph if `GEMINI_API_KEY` is set **when it starts**, either exported in your shell or in `cs4b/.env` (gitignored). Both graphs share one MCP client. Start it the same way:

```bash
uvicorn api.main:app --port 8000
```

- `GET /health` reports `modes.live.available`. If live is unavailable, it gives the reason.
- Each request picks its mode with `"mode": "replay" | "live"` (default `replay`). Asking for live without a key returns **400** `live_unavailable`.
- A thread keeps the mode it started in. Asking with the other mode starts a new thread, and the response has `thread_reset: true` and `previous_thread_id`.
- In live mode, requests that were already recorded still replay for free. `fresh_model_calls` says how many calls really reached Gemini, and the UI tags those answers "Live" rather than "Live · cached".
- The key is never logged or returned. Gemini errors come back as **502** `live_error` with any key-shaped text redacted.

Live answers are written to `outputs/cache/` as new files. **Don't commit them.** `git status outputs/cache` shows them. `git clean -n outputs/cache` previews removing them, and `git clean -f outputs/cache` removes them.

## 2. Frontend
In a second terminal:

```bash
cd cs4b/frontend
```

```bash
npm install
```

```bash
npm run dev
```

Open http://localhost:5173. The dev server proxies `/api/*` to `http://127.0.0.1:8000`. Set `VITE_API_TARGET` to point it somewhere else.

Production build: `npm run build`, then `npm run preview` (serves `dist/` on :4173 with the same proxy).

## 3. Tests
From `cs4b/`:

```bash
pytest -q api/tests
```

The 31 tests run through FastAPI's `TestClient` with no key (`api/tests/test_api.py`, `api/tests/test_modes.py`). They cover:
- every endpoint, and that the ten recorded answers match `outputs/questions/`
- the q02 → q03 follow-up on one thread
- 409 on a cache miss, 422 on bad input, 404 on an unknown thread
- CORS and the OpenAPI response models
- a repair (a refused query, then a retry) using the kit's stand-in model
- a scan that fails if `api/` or `frontend/` imports `sqlite3` or names the database file
- modes: replay is the default; live without a key returns 400 (on `/ask` and `/conversations`); `/health` reports it
- switching mode starts a new thread, and both threads keep their own history; the same mode keeps the thread
- the key is never returned, even inside a Gemini error, which is redacted

Live mode in tests is played by the kit's stand-in model, so nothing is called and nothing is cached.

The original grader commands are unaffected: `python tests/run_tests.py`, `pytest -q tests/`, `PYTHONPATH=src python -m askpanel.check`.

## API

| Method | Path | Body / returns |
|---|---|---|
| GET | `/health` | `default_mode`, `modes.{replay,live}.{available,reason}`, model, MCP tools, cache size |
| GET | `/questions` | the ten questions from `questions/questions.yaml` |
| POST | `/ask` | `{question, thread_id?, mode?}` → thread_id, mode, thread_reset, previous_thread_id, turn, answer, declined, decline_reason, explanation, sql, columns, rows, row_count, truncated, usd, tokens, model_calls, fresh_model_calls, attempts, stop, error, trace |
| POST | `/conversations` | `{mode?}` → `{thread_id, mode}` (201) |
| GET | `/conversations/{thread_id}` | the thread's mode and turns, read from that mode's LangGraph checkpointer (404 if unknown) |
| GET | `/schema` | tables and column descriptions via MCP `list_tables` + `describe_table` |
| GET | `/economics` | the five lines of `outputs/economics.md` plus totals recomputed with `askpanel.econ` |

Errors all have the shape `{"detail": {"code", "message"}}`:
- `400 live_unavailable`: live mode was asked for but the API has no key.
- `409 cache_miss`: replay has no recording for this request.
- `502 live_error`: the Gemini call failed.

- `attempts` counts the failed attempts that went down the repair edge (0 means the first try worked).
- `model_calls` counts `generate` steps.
- Conversations live in memory (`InMemorySaver`), so restarting the API forgets them.

## Replay rules worth knowing
- An answer replays only if the **exact** request was recorded: the question text, schema, rules and conversation history.
- A follow-up (q03) replays only right after the question it follows (q02) on the **same** thread. The sidebar's **Demo follow-up** button does exactly this.
- Anything else in replay returns 409. The UI shows a friendly message and highlights the recorded questions.

## Front-end features
- **Sidebar:** the ten recorded questions (click to ask), **New conversation**, **Demo follow-up (q02 → q03)**, and the current thread id.
- **Answer card:**
  - the answer text and the model's explanation
  - the SQL, highlighted and formatted, with a copy button
  - the rows as a sortable table: click a header to cycle through first direction, other direction, unsorted
  - badges for cost, model calls, repairs, tokens, rows and turn
- **Trace timeline:** each node step with its outcome. A refused check or execute shows in red with "goes back to the model", and the retry shows as "repair attempt N". It opens automatically when a repair happened.
- **Declines** get an amber card with no SQL or table.
- **Header:** a **Replay | Live** switch, the conversation's running cost, the Schema / Economics panel, and a light/dark toggle (follows the system, remembers your choice).
  - Live is locked, with a tooltip giving the server's reason, when `/health` says it's unavailable.
  - Switching mode starts a new conversation automatically.
- **Mode tag** on every answer card: Replay, Live, or Live · cached.
