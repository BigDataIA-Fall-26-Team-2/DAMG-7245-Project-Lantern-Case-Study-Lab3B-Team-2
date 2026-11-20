"""Ask the Panel: the analyst's interface (Lab 36B).

    streamlit run app/streamlit_app.py

Replay mode is the default: answers come from outputs/cache/, with no key and no
cost. The app calls the same LangGraph agent as agent/run.py, and the agent reaches
the data only through the MCP server.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent  # noqa: E402,F401  (paths)

import os  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from agent import ROOT  # noqa: E402
from agent.graph import ask, build_graph, model_calls  # noqa: E402
from agent.mcp_client import PanelClient  # noqa: E402
from agent.model import PARAMS, load_key, make_model  # noqa: E402
from askpanel import clock, llm, questions, standin  # noqa: E402

STANDIN = os.environ.get("ASKPANEL_STANDIN") == "1"   # offline fixture development only

st.set_page_config(page_title="Ask the Panel", layout="wide")


@st.cache_resource
def client():
    return PanelClient()


@st.cache_resource
def graph(mode):
    """One compiled graph per mode; its checkpointer holds every conversation."""
    if STANDIN:
        return build_graph(standin.FixtureSQLModel(), client().tools(), clock.clock, PARAMS,
                           model_name="stand-in")
    return build_graph(make_model(mode), client().tools(), clock.clock, PARAMS)


def recorded_questions():
    try:
        return questions.load(ROOT / "questions/questions.yaml")
    except FileNotFoundError:
        return []


ss = st.session_state
ss.setdefault("conv", 1)
ss.setdefault("messages", [])
ss.setdefault("pending", None)

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Ask the Panel")
    panel = PARAMS["data"]["real_panel"] if PARAMS["data"].get("use_real") else PARAMS["data"]["panel"]
    st.caption(f"Panel: `{panel}`  \nModel: `{'stand-in' if STANDIN else PARAMS['model']['name']}`")
    has_key = bool(load_key())
    mode = st.radio("Model mode", ["replay", "record"], index=0, horizontal=True,
                    help="replay: recorded answers only, free and offline. "
                         "record: calls Gemini for questions not yet recorded (needs GEMINI_API_KEY).")
    if mode == "record" and not has_key:
        st.warning("No GEMINI_API_KEY found: using replay.")
        mode = "replay"
    if st.button("New conversation", width="stretch"):
        ss.conv += 1
        ss.messages = []
        st.rerun()
    st.caption(f"Conversation #{ss.conv}")
    turns = [m for m in ss.messages if m["role"] == "assistant"]
    if turns:
        st.metric("Conversation cost (USD)", f"{sum(m['usd'] for m in turns):.6f}")
        st.metric("Model calls", sum(m["calls"] for m in turns))
    qs = recorded_questions()
    if qs:
        st.subheader("Recorded questions")
        st.caption("These replay from the cache. A follow-up replays only after the question "
                   "it follows, in the same conversation.")
        for q in qs:
            tag = f"{q['id']} {q['category']}" + (f" (after {q['follows']})" if q.get("follows") else "")
            if st.button(f"{tag}: {q['question']}", key=f"q-{q['id']}", width="stretch"):
                ss.pending = q["question"]


def show(m):
    """One assistant turn: answer, SQL, rows, cost and calls, trace."""
    if m.get("error"):
        st.error(m["error"])
        return
    st.markdown(m["answer"].replace("\n", "  \n") if m.get("decline") is None else m["answer"])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cost (USD)", f"{m['usd']:.6f}")
    c2.metric("Model calls", m["calls"])
    c3.metric("Tokens", f"{m['tokens']:,}")
    c4.metric("Rows", m["result"]["row_count"] if m.get("result") else 0)
    if m.get("sql"):
        st.code(m["sql"], language="sql")
    if m.get("result") and m["result"]["rows"]:
        r = m["result"]
        cols, seen = [], {}
        for c in r["columns"]:                       # unique headers for the table widget
            seen[c] = seen.get(c, 0) + 1
            cols.append(c if seen[c] == 1 else f"{c}_{seen[c]}")
        st.dataframe(pd.DataFrame(r["rows"], columns=cols), width="stretch",
                     hide_index=True)
        if r.get("truncated"):
            st.caption(f"Truncated at the server's row cap ({PARAMS['server']['max_rows']}).")
    with st.expander("Trace"):
        st.dataframe(pd.DataFrame(m["trace"]).drop(columns=["run_id"], errors="ignore"),
                     width="stretch", hide_index=True)


# ------------------------------------------------------------------ conversation
st.title("Ask the Panel")
st.caption("Questions about the BDC holdings panel. Every answer shows the SQL behind it; "
           "the agent reads through one read-only MCP server and never writes.")

for m in ss.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["text"]) if m["role"] == "user" else show(m)

q = st.chat_input("Ask about the BDC holdings") or ss.pending
ss.pending = None
if q:
    ss.messages.append({"role": "user", "text": q})
    with st.chat_message("user"):
        st.markdown(q)
    with st.chat_message("assistant"):
        turn = sum(m["role"] == "user" for m in ss.messages)
        try:
            with st.spinner("Thinking..."):
                s = ask(graph(mode), q, thread_id=f"conv-{ss.conv}", run_id=f"conv-{ss.conv}-{turn}")
            query = s.get("query") or {}
            m = {"role": "assistant", "answer": s["answer"], "sql": query.get("sql"),
                 "decline": query.get("decline"), "result": s.get("result"),
                 "usd": s.get("usd", 0.0), "tokens": s.get("tokens", 0),
                 "calls": model_calls(s), "trace": s["trace"]}
        except llm.CacheMiss:
            m = {"role": "assistant", "usd": 0.0, "calls": 0, "error": (
                "Not in the replay cache: this exact question (with this conversation's history) "
                "was never recorded. Switch to record mode with a GEMINI_API_KEY, or pick a "
                "recorded question.")}
        show(m)
    ss.messages.append(m)
    st.rerun()                                  # refresh the sidebar totals
