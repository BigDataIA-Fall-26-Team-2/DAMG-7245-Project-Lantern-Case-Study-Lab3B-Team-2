"""Ask the Panel HTTP API.

    cd cs4b && uvicorn api.main:app --port 8000     # Swagger UI at /docs

Replay is the default mode and needs no key. If GEMINI_API_KEY is set when the API
starts, live mode is also available per request ("mode": "live"). The agent graphs
are built once at startup; all data goes over MCP to services/mcp/server.py.
"""
import sys
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # cs4b/

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from api import schemas as S  # noqa: E402
from api.service import (CACHE_MISS_MESSAGE, CacheMissError, LiveCallError,  # noqa: E402
                         LiveUnavailable, PanelService, UnknownThread, economics)

DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173",
               "http://localhost:4173", "http://127.0.0.1:4173"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.panel = PanelService()          # one MCP session; replay graph (+ live if keyed)
    try:
        yield
    finally:
        app.state.panel.close()


app = FastAPI(
    title="Ask the Panel API",
    version="1.1.0",
    summary="Natural-language questions over the Lab 3B BDC holdings panel.",
    description=(
        "A LangGraph agent writes one SQL query as a Pydantic object; a read-only MCP server "
        "runs it. Every answer comes with its SQL, rows, cost and node-by-node trace.\n\n"
        "**Modes.** `replay` (default) answers only requests recorded in `outputs/cache/`; any "
        "other question returns **409** `cache_miss`. `live` calls Gemini for new requests and "
        "is available only if `GEMINI_API_KEY` was set when the API started (otherwise **400** "
        "`live_unavailable`). `GET /health` lists the available modes.\n\n"
        "**Threads.** Follow-ups reuse the `thread_id` of the question they follow. A thread keeps "
        "the mode it started in; asking with the other mode starts a new thread "
        "(`thread_reset: true`)."),
    lifespan=lifespan,
    openapi_tags=[{"name": "meta", "description": "Status, recorded questions, schema, economics"},
                  {"name": "ask", "description": "Ask questions and manage conversations"}],
)

extra = [o.strip() for o in os.environ.get("ASKPANEL_CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=DEV_ORIGINS + extra,
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


def panel(request: Request) -> PanelService:
    return request.app.state.panel


def _live_unavailable(e: LiveUnavailable):
    return HTTPException(400, {"code": "live_unavailable", "message": str(e)})


@app.get("/health", response_model=S.Health, tags=["meta"], summary="Service status and available modes")
def health(request: Request):
    return panel(request).health()


@app.get("/questions", response_model=list[S.RecordedQuestion], tags=["meta"],
         summary="The ten recorded questions (questions/questions.yaml)")
def recorded_questions(request: Request):
    return [{k: q.get(k) for k in ("id", "category", "question", "follows")}
            for q in panel(request).questions]


@app.get("/schema", response_model=S.Schema, tags=["meta"],
         summary="Tables and column descriptions, via MCP list_tables and describe_table")
def schema(request: Request):
    return panel(request).schema()


@app.get("/economics", response_model=S.Economics, tags=["meta"],
         summary="Unit economics: outputs/economics.md plus totals from askpanel.econ")
def get_economics():
    return economics()


@app.post("/ask", response_model=S.AskResponse, tags=["ask"], summary="Ask one question",
          responses={400: {"model": S.ErrorResponse, "description": "Live mode requested but unavailable"},
                     409: {"model": S.ErrorResponse, "description": "Replay: not in the replay cache"},
                     502: {"model": S.ErrorResponse, "description": "Live: the Gemini call failed"}})
def post_ask(body: S.AskRequest, request: Request):
    try:
        return panel(request).ask(body.question, body.thread_id, body.mode)
    except LiveUnavailable as e:
        raise _live_unavailable(e) from None
    except CacheMissError:
        raise HTTPException(409, {"code": "cache_miss", "message": CACHE_MISS_MESSAGE}) from None
    except LiveCallError as e:
        raise HTTPException(502, {"code": "live_error",
                                  "message": f"The Gemini call failed: {e}"}) from None


@app.post("/conversations", response_model=S.Conversation, status_code=201, tags=["ask"],
          summary="Start a new conversation (thread) in a mode",
          responses={400: {"model": S.ErrorResponse, "description": "Live mode requested but unavailable"}})
def new_conversation(request: Request, body: Optional[S.ConversationCreate] = None):
    mode = (body or S.ConversationCreate()).mode
    try:
        return {"thread_id": panel(request).new_thread(mode), "mode": mode}
    except LiveUnavailable as e:
        raise _live_unavailable(e) from None


@app.get("/conversations/{thread_id}", response_model=S.ConversationHistory, tags=["ask"],
         summary="A conversation's mode and turns, from the LangGraph checkpointer",
         responses={404: {"model": S.ErrorResponse, "description": "Unknown thread"}})
def get_conversation(thread_id: str, request: Request):
    try:
        return panel(request).history(thread_id)
    except UnknownThread:
        raise HTTPException(404, {"code": "unknown_thread",
                                  "message": f"no conversation {thread_id!r}"}) from None
