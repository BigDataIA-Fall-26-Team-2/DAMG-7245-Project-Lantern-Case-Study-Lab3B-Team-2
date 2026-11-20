"""The agent behind the API: built once, shared by every request.

Reuses the Lab 4B code unchanged: agent.graph (StateGraph + InMemorySaver),
agent.model (ReplayClient over outputs/cache), agent.mcp_client (PanelClient,
in-memory MCP session to services/mcp/server.py). Nothing here opens the
database: every read goes over MCP to the server, which owns the read-only
connection.

Two graphs share ONE MCP client:
  replay: ReplayClient(mode="replay"), always built; answers only cached requests.
  live:   ReplayClient(mode="record") over Gemini, built only if GEMINI_API_KEY is set;
          cached requests still replay for free, new ones call Gemini and are stored.
A thread belongs to one mode for its whole life; asking in the other mode starts a
new thread. The API key is never logged, stored on this object, or returned.
"""
import json
import re
import threading
import uuid
from pathlib import Path
from typing import Optional

import agent  # noqa: F401  (puts cs4b/ and cs4b/src on sys.path)
from agent import ROOT
from agent.graph import ask, build_graph, model_calls
from agent.mcp_client import PanelClient
from agent.model import PARAMS, load_key, make_model
from askpanel import clock, econ, llm, questions

MODES = ("replay", "live")
CACHE_MISS_MESSAGE = ("This question isn't in the replay cache. Try one of the recorded "
                      "questions, or switch to live mode with a Gemini key.")
NO_KEY_REASON = ("Live mode isn't available: no GEMINI_API_KEY was set when the API started. "
                 "Export GEMINI_API_KEY (or put it in cs4b/.env) and restart the API.")


class CacheMissError(Exception):
    pass


class UnknownThread(KeyError):
    pass


class LiveUnavailable(Exception):
    pass


class LiveCallError(Exception):
    """A failed Gemini call; the message is already scrubbed of the key."""


class _Recorder:
    """Wraps the live ReplayClient and notes which requests were NOT already cached,
    so an answer can say whether Gemini was really called (or it replayed for free)."""

    def __init__(self, inner, cache_dir: Path):
        self.inner, self.dir = inner, Path(cache_dir)
        self.fresh: set[str] = set()
        self._lock = threading.Lock()

    def __call__(self, req):
        key = llm.request_key(req)
        hit = (self.dir / f"{key}.json").exists()
        out = self.inner(req)
        if not hit:
            with self._lock:
                self.fresh.add(key)
        return out

    def take(self, keys) -> int:
        with self._lock:
            n = sum(k in self.fresh for k in keys)
            self.fresh.difference_update(keys)
        return n


def scrub(text: str) -> str:
    """Remove the API key (and anything key-shaped) from a message."""
    key = load_key()
    if key:
        text = text.replace(key, "[redacted]")
    return re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "[redacted]", text)


class PanelService:
    def __init__(self, replay_model=None, live_model=None, model_name=None):
        """replay_model / live_model: tests inject the kit's stand-in. Without live_model,
        the live graph is built only when a Gemini key exists."""
        self.client = PanelClient()                       # ONE MCP session for both graphs
        tools, name = self.client.tools(), model_name
        cache = ROOT / PARAMS["model"]["cache_dir"]
        self.graphs = {"replay": build_graph(replay_model or make_model("replay"), tools,
                                             clock.clock, PARAMS, model_name=name)}
        self.live_reason: Optional[str] = None
        self._recorder: Optional[_Recorder] = None
        if live_model is None and not load_key():
            self.live_reason = NO_KEY_REASON
        else:
            try:
                inner = live_model or make_model("record")    # GeminiCall reads the key itself
            except Exception as e:                            # noqa: BLE001
                inner, self.live_reason = None, f"Live mode failed to start: {scrub(str(e))}"
            if inner is not None:
                self._recorder = _Recorder(inner, cache)
                self.graphs["live"] = build_graph(self._recorder, tools, clock.clock, PARAMS,
                                                  model_name=name)
        self.questions = questions.load(ROOT / "questions/questions.yaml")
        self._thread_mode: dict[str, str] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def close(self):
        self.client.close()

    def available(self, mode: str) -> bool:
        return mode in self.graphs

    # ------------------------------------------------------------ info
    def health(self):
        cache = ROOT / PARAMS["model"]["cache_dir"]
        return {"status": "ok", "default_mode": "replay",
                "modes": {"replay": {"available": True, "reason": None},
                          "live": {"available": self.available("live"), "reason": self.live_reason}},
                "model": PARAMS["model"]["name"], "mcp_server": "askpanel-query",
                "tools": self.client.list_tool_names(),
                "cached_responses": len(list(cache.glob("*.json"))),
                "recorded_questions": len(self.questions)}

    def schema(self):
        return {"tables": [{"table": t, "columns": self.client.describe_table(t)}
                           for t in self.client.list_tables()]}

    # ------------------------------------------------------------ conversations
    def _require(self, mode):
        if mode not in MODES:
            raise ValueError(mode)
        if not self.available(mode):
            raise LiveUnavailable(self.live_reason or NO_KEY_REASON)

    def new_thread(self, mode: str = "replay") -> str:
        self._require(mode)
        tid = f"c-{uuid.uuid4().hex[:12]}"
        with self._guard:
            self._thread_mode[tid] = mode
            self._locks[tid] = threading.Lock()
        return tid

    def thread_mode(self, tid) -> Optional[str]:
        with self._guard:
            return self._thread_mode.get(tid)

    def _claim(self, tid, mode) -> threading.Lock:
        with self._guard:
            self._thread_mode.setdefault(tid, mode)
            return self._locks.setdefault(tid, threading.Lock())

    def _turns(self, tid, mode):
        """Completed turns, oldest first, read from that mode's checkpointer."""
        cfg = {"configurable": {"thread_id": tid}}
        done = [s.values for s in self.graphs[mode].get_state_history(cfg) if s.next == () and s.values]
        return list(reversed(done))

    def history(self, tid):
        mode = self.thread_mode(tid)
        if mode is None:
            raise UnknownThread(tid)
        out = []
        for i, v in enumerate(self._turns(tid, mode), 1):
            q = v.get("query") or {}
            out.append({"turn": i, "question": v.get("question"), "answer": v.get("answer"),
                        "sql": q.get("sql"), "declined": q.get("sql") is None and bool(q.get("decline")),
                        "usd": round(v.get("usd", 0.0), 8), "model_calls": model_calls(v)})
        return {"thread_id": tid, "mode": mode, "turns": out}

    # ------------------------------------------------------------ ask
    def ask(self, question: str, thread_id: Optional[str] = None, mode: str = "replay"):
        self._require(mode)
        previous, tid = None, thread_id
        if tid is not None and self.thread_mode(tid) not in (None, mode):
            previous, tid = tid, None                     # never mix modes on one thread
        if tid is None:
            tid = self.new_thread(mode)
        graph = self.graphs[mode]
        with self._claim(tid, mode):                      # one turn at a time per thread
            turn = len(self._turns(tid, mode)) + 1
            try:
                s = ask(graph, question, thread_id=tid, run_id=f"{tid}-{turn}")
            except llm.CacheMiss as e:
                raise CacheMissError(str(e)) from None
            except Exception as e:                        # noqa: BLE001  (a live provider failure)
                if mode == "live":
                    raise LiveCallError(scrub(f"{type(e).__name__}: {e}")[:500]) from None
                raise
        keys = [t["request_key"] for t in s.get("trace", []) if t.get("node") == "generate"]
        fresh = self._recorder.take(keys) if mode == "live" and self._recorder else 0
        q, r = s.get("query") or {}, s.get("result") or {}
        declined = q.get("sql") is None and bool(q.get("decline")) and not s.get("error")
        return {"thread_id": tid, "mode": mode, "thread_reset": previous is not None,
                "previous_thread_id": previous, "turn": turn, "question": question,
                "answer": s.get("answer") or "",
                "declined": declined, "decline_reason": q.get("decline") if declined else None,
                "explanation": q.get("explanation") or None, "sql": q.get("sql"),
                "columns": r.get("columns", []), "rows": r.get("rows", []),
                "row_count": r.get("row_count", 0), "truncated": bool(r.get("truncated")),
                "usd": round(s.get("usd", 0.0), 8), "tokens": s.get("tokens", 0),
                "model_calls": model_calls(s), "fresh_model_calls": fresh,
                "attempts": s.get("attempt", 0), "stop": s.get("stop"), "error": s.get("error"),
                "trace": [{k: v for k, v in t.items() if k != "run_id"} for t in s.get("trace", [])]}


# ---------------------------------------------------------------- economics
_ROW = re.compile(r"^\|\s*(?!Line\b|-)([^|]+?)\s*\|\s*(.+?)\s*\|\s*$")


def economics():
    """The five lines of outputs/economics.md plus totals recomputed from outputs/questions/."""
    md = (ROOT / "outputs/economics.md").read_text(encoding="utf-8")
    lines = [{"line": m.group(1), "value": m.group(2)}
             for m in map(_ROW.match, md.splitlines()) if m and m.group(1) in econ.FIVE_LINES]
    saved = [json.loads(p.read_text(encoding="utf-8"))
             for p in sorted((ROOT / "outputs/questions").glob("q*.json"))]
    e = PARAMS["economics"]
    minutes, rate = float(e["analyst_minutes_per_question"]), float(e["analyst_rate_usd"])
    computed = {**econ.summary(saved), "tokens_total": sum(o.get("tokens", 0) for o in saved),
                "analyst_minutes_per_question": minutes, "analyst_rate_usd": rate,
                "hours_saved": econ.hours_saved_table(minutes / 60, rate, len(saved))}
    return {"source": "outputs/economics.md", "lines": lines, "computed": computed}
