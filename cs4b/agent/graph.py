r"""The Ask the Panel agent as a LangGraph StateGraph (Lab 35B).

    load_schema -> generate -> check --ok--> execute --ok--> summarize -> END
                      ^          |  \--decline----------------^
                      +--repair--+------repair---+   (capped at agent.max_attempts)

The nodes are the kit's askpanel.nodes.make_nodes, except check, which validates
the model's reply with our Pydantic contract (agent.contract.validate_query) so the
gate's refusal code reaches the repair edge. The checkpointer keeps each thread's
history, so a follow-up sees the questions and SQL before it.
"""
from typing import Optional, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from agent import ROOT  # noqa: F401  (puts src/ on sys.path)
from agent.contract import validate_query
from askpanel import nodes as kit


class AskState(TypedDict, total=False):
    question: str
    history: list
    schema: str
    attempt: int
    query: Optional[dict]
    error: Optional[dict]
    result: Optional[dict]
    answer: Optional[str]
    trace: list            # returned whole by each node: default (overwrite) reducer
    usd: float
    tokens: int
    stop: Optional[str]
    run_id: str


def contract_check(clock):
    """The check node, over validate_query. Same trace record as the kit's."""
    def check(state):
        def rec(**kw):
            return state["trace"] + [{"run_id": state["run_id"], "step": len(state["trace"]) + 1,
                                      "ts": clock().isoformat(), "node": "check", **kw}]
        q = state["query"] or {}
        model, err = validate_query(q)
        if err:
            return {"error": err, "attempt": state["attempt"] + 1,
                    "trace": rec(outcome=err["code"])}
        if model.sql is None:
            return {"query": {**q, "sql": None, "decline": model.decline},
                    "trace": rec(outcome="decline")}
        return {"query": {**q, "sql": model.sql, "decline": None}, "trace": rec(outcome="ok")}
    return check


VALUE_COLUMNS = ["bdc", "investment_type"]     # spelled out for the model (failures 1 and 2)


def schema_with_values(load_schema, tools):
    """The kit's load_schema, plus the exact values of a few columns (fetched through
    the MCP server's sample_values tool) and the prompt rules. Everything the model
    reads is in state["schema"], so it is inside the request and its cache key:
    changing a rule or a value can never replay a stale answer."""
    from agent.model import RULES

    def node(state):
        out = load_schema(state)
        lines = [out["schema"], "", "Exact values (holdings_v):"]
        for col in VALUE_COLUMNS:
            vals = tools["sample_values"](table="holdings_v", column=col, limit=200)
            lines.append(f"- {col}: " + ("; ".join(map(str, vals)) if vals else "(always NULL)"))
        schema = "\n".join(lines + ["", RULES])
        tr = out["trace"][:-1] + [{**out["trace"][-1], "schema_hash": kit.h12(schema)}]
        return {"schema": schema, "trace": tr}
    return node


def build_graph(model, tools, clock, params, model_name=None, checkpointer=None):
    """model: a ReplayClient (agent.model.make_model). tools: the MCP client's four calls."""
    a = params["agent"]
    n, route_after_check, route_after_execute = kit.make_nodes(
        model, tools, clock, model_name=model_name or params["model"]["name"],
        max_attempts=a["max_attempts"], usd_cap=a["usd_cap_per_question"],
        token_cap=a["token_cap_per_question"], allowed=set(params["server"]["tables"]))

    g = StateGraph(AskState)
    g.add_node("load_schema", schema_with_values(n["load_schema"], tools))
    g.add_node("generate", n["generate"])
    g.add_node("check", contract_check(clock))
    g.add_node("execute", n["execute"])
    g.add_node("summarize", n["summarize"])
    g.add_edge(START, "load_schema")
    g.add_edge("load_schema", "generate")
    g.add_edge("generate", "check")
    g.add_conditional_edges("check", route_after_check,
                            {"execute": "execute", "generate": "generate", "summarize": "summarize"})
    g.add_conditional_edges("execute", route_after_execute,
                            {"generate": "generate", "summarize": "summarize"})
    g.add_edge("summarize", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())


def ask(app, question, thread_id, run_id=None):
    """One turn on a thread: the thread's history goes into the new state."""
    cfg = {"configurable": {"thread_id": thread_id}}
    prev = app.get_state(cfg).values.get("history", [])
    return app.invoke(kit.new_state(question, prev, run_id=run_id or thread_id), cfg)


def model_calls(state):
    return sum(t.get("node") == "generate" for t in state.get("trace", []))
