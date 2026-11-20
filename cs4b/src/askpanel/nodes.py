"""The agent's nodes, as plain functions over a state dict, and the two
routing functions. Lab 35B wires exactly these into a LangGraph StateGraph;
run_plain() runs the same graph without LangGraph, for tests and notebooks.

Graph:  load_schema -> generate -> check --ok--> execute --ok--> summarize
                           ^          |               |
                           +--repair--+------repair---+   (capped)

Each node returns only the keys it changes (LangGraph merges them). Lists
such as trace are returned whole, so keep LangGraph's default (overwrite)
reducer for them: an operator.add reducer would double every record.
"""
import hashlib
import json

from . import gate, llm

SYSTEM = ("You translate an analyst's question about BDC holdings into ONE "
          "SQLite SELECT over the tables described. Use only those tables and "
          "columns. If the data cannot answer the question, decline. Reply as "
          'JSON: {"sql": "...", "explanation": "..."} or '
          '{"sql": null, "decline": "reason"}.')
STATE_KEYS = ["question", "history", "schema", "attempt", "query", "error",
              "result", "answer", "trace", "usd", "tokens", "stop", "run_id"]


def h12(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str)
                          .encode()).hexdigest()[:12]


def build_request(state, model_name):
    """The exact request the model sees. ReplayClient keys on all of it."""
    return {"model": model_name, "system": SYSTEM,
            "schema": state["schema"], "history": state.get("history", []),
            "question": state["question"], "attempt": state.get("attempt", 0),
            "error": state.get("error"),
            "prior_sql": (state.get("query") or {}).get("sql")
            if state.get("error") else None}


def new_state(question, history=None, run_id="run-1"):
    return {"question": question, "history": list(history or []), "schema": "",
            "attempt": 0, "query": None, "error": None, "result": None,
            "answer": None, "trace": [], "usd": 0.0, "tokens": 0, "stop": None,
            "run_id": run_id}


def make_nodes(model, tools, clock, model_name="stand-in",
               max_attempts=3, usd_cap=0.10, token_cap=30_000,
               allowed=gate.ALLOWED_TABLES):
    """model: callable(request) -> dict (a ReplayClient in record or replay
    mode, or the stand-in). tools: name -> callable, i.e. your MCP client's
    calls. Returns (nodes, route_after_check, route_after_execute)."""

    def rec(state, node, **kw):
        return state["trace"] + [{"run_id": state["run_id"],
                                  "step": len(state["trace"]) + 1,
                                  "ts": clock().isoformat(), "node": node, **kw}]

    def load_schema(state):
        parts = []
        for t in tools["list_tables"]():
            cols = tools["describe_table"](table=t)
            parts.append(f"{t}(" + ", ".join(
                f"{c['column']}: {c['description']}" if c["description"]
                else c["column"] for c in cols) + ")")
        schema = "\n".join(parts)
        return {"schema": schema,
                "trace": rec(state, "load_schema", schema_hash=h12(schema))}

    def generate(state):
        req = build_request(state, model_name)
        out = model(req)
        usd = state["usd"] + out.get("usd", 0.0)
        toks = state["tokens"] + out.get("tokens_in", 0) + out.get("tokens_out", 0)
        query = {"sql": out.get("sql"), "decline": out.get("decline"),
                 "explanation": out.get("explanation", "")}
        tr = rec(state, "generate", attempt=state["attempt"],
                 request_key=llm.request_key(req), usd=out.get("usd", 0.0),
                 tokens_in=out.get("tokens_in", 0), tokens_out=out.get("tokens_out", 0),
                 sql_hash=h12(query["sql"]) if query["sql"] else None)
        stop = None
        if usd > usd_cap:
            stop = "budget_usd"
        elif toks > token_cap:
            stop = "budget_tokens"
        return {"query": query, "usd": usd, "tokens": toks, "trace": tr,
                "stop": stop, "error": None, "result": None}

    def check(state):
        q = state["query"]
        if q["sql"] is None and not q.get("decline"):
            return {"error": {"code": "invalid", "detail": "reply had neither sql nor decline"},
                    "attempt": state["attempt"] + 1,
                    "trace": rec(state, "check", outcome="invalid")}
        if q["sql"] is None:
            return {"trace": rec(state, "check", outcome="decline")}
        try:
            sql = gate.static_check(q["sql"], allowed)
        except gate.GateError as e:
            return {"error": {"code": e.code, "detail": e.detail},
                    "attempt": state["attempt"] + 1,
                    "trace": rec(state, "check", outcome=e.code)}
        return {"query": {**q, "sql": sql}, "trace": rec(state, "check", outcome="ok")}

    def execute(state):
        try:
            r = tools["run_query"](sql=state["query"]["sql"])
        except Exception as e:                       # refusals are observations
            code = getattr(e, "code", type(e).__name__)
            return {"error": {"code": code, "detail": str(e)},
                    "attempt": state["attempt"] + 1,
                    "trace": rec(state, "execute", outcome=code)}
        return {"result": r, "trace": rec(state, "execute", outcome="ok",
                                          rows=r["row_count"], result_hash=h12(r["rows"]))}

    def summarize(state):
        q, r, err = state["query"] or {}, state["result"], state["error"]
        if state.get("stop"):
            ans = f"Stopped ({state['stop']}) before an answer."
        elif q.get("sql") is None and q.get("decline"):
            ans = q["decline"]
        elif err or r is None:
            code = err["code"] if err else "no_result"
            ans = f"I could not answer that: {code} after {state['attempt']} attempt(s)."
        else:
            ans = format_answer(r)
        hist = state["history"] + [{"question": state["question"], "sql": q.get("sql")}]
        return {"answer": ans, "history": hist,
                "trace": rec(state, "summarize", stop=state.get("stop"))}

    def _repair_or(state, nxt):
        if state.get("stop"):
            return "summarize"
        if state.get("error"):
            return "generate" if state["attempt"] < max_attempts else "summarize"
        return nxt

    def route_after_check(state):
        if (state["query"] or {}).get("sql") is None and not state.get("error"):
            return "summarize"                       # a decline
        return _repair_or(state, "execute")

    def route_after_execute(state):
        return _repair_or(state, "summarize")

    nodes = {"load_schema": load_schema, "generate": generate, "check": check,
             "execute": execute, "summarize": summarize}
    return nodes, route_after_check, route_after_execute


def format_answer(r, n=5):
    if not r["rows"]:
        return "No rows match."
    head = " | ".join(r["columns"])
    def cell(v):
        if v is None:
            return ""
        if isinstance(v, float):
            return f"{v:,.2f}" if abs(v) >= 100 else f"{v:.4g}"
        return str(v)
    lines = [" | ".join(cell(v) for v in row) for row in r["rows"][:n]]
    more = (f"\n... {r['row_count'] - n} more row(s)" if r["row_count"] > n else "")
    more += " (truncated at the row cap)" if r.get("truncated") else ""
    return f"{r['row_count']} row(s)\n{head}\n" + "\n".join(lines) + more


def run_plain(state, nodes, route_after_check, route_after_execute, max_hops=20):
    """The same graph as Lab 35B's StateGraph, without LangGraph."""
    s = dict(state)
    nxt = "load_schema"
    for _ in range(max_hops):
        s.update(nodes[nxt](s))
        if nxt == "summarize":
            return s
        nxt = {"load_schema": lambda: "generate", "generate": lambda: "check",
               "check": lambda: route_after_check(s),
               "execute": lambda: route_after_execute(s)}[nxt]()
    raise RuntimeError("graph did not terminate")
