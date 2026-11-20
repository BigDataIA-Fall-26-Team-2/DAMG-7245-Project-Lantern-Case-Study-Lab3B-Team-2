"""Part 3 (Lab 35B): the LangGraph agent, over the MCP server, on the fixture.

    pytest -q tests/test_agent.py

Uses the kit's deterministic stand-in model behind a scratch ReplayClient, so it
needs no key and leaves outputs/cache alone.
"""
import json
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from agent.graph import ask, build_graph, model_calls  # noqa: E402
from agent.mcp_client import PanelClient  # noqa: E402
from askpanel import clock, db, llm, standin  # noqa: E402
from services.mcp import server  # noqa: E402

P = yaml.safe_load((ROOT / "params.yaml").read_text())
TMP = Path(tempfile.mkdtemp())
DB = db.build_db(db.load_panel(ROOT / "data/fixture/panel_2p.csv"), TMP / "agent.sqlite",
                 (ROOT / "sql/holdings_v.sql").read_text())
PIK = "Which current debt holdings carry a PIK rate above 2%?"
COUNT = "How many current holdings does each BDC report?"


@pytest.fixture(scope="module")
def client():
    server.configure(db_path=DB)
    c = PanelClient()
    yield c
    c.close()
    server.configure()


def graph(client, model, **over):
    params = {**P, "agent": {**P["agent"], **over}}
    return build_graph(model, client.tools(), clock.clock, params, model_name="stand-in")


def test_answer_through_the_server(client):
    s = ask(graph(client, standin.FixtureSQLModel()), COUNT, "t1")
    assert s["result"]["row_count"] == 4 and model_calls(s) == 1
    assert [t["node"] for t in s["trace"]] == ["load_schema", "generate", "check", "execute", "summarize"]


def test_repair_edge_carries_the_servers_code(client):
    seen = []
    base = standin.FixtureSQLModel()

    def spy(req):
        seen.append(req)
        return base(req)
    s = ask(graph(client, spy), PIK, "t2")
    outcomes = [(t["node"], t.get("outcome")) for t in s["trace"]]
    assert ("execute", "invalid") in outcomes and s["result"] is not None
    assert model_calls(s) == 2
    assert seen[1]["error"]["code"] == "invalid" and "pik" in seen[1]["error"]["detail"]
    assert seen[1]["prior_sql"].startswith("SELECT")


def test_contract_code_reaches_the_graph(client):
    bad = standin.FixtureSQLModel(answers={COUNT: ["DELETE FROM holdings",
                                                   standin.FIXTURE[COUNT][0]]})
    s = ask(graph(client, bad), COUNT, "t3")
    assert ("check", "not_select") in [(t["node"], t.get("outcome")) for t in s["trace"]]
    assert s["result"]["row_count"] == 4


def test_repair_is_capped(client):
    always_bad = standin.FixtureSQLModel(answers={COUNT: ["SELECT nope FROM holdings_v"]})
    s = ask(graph(client, always_bad, max_attempts=3), COUNT, "t4")
    assert model_calls(s) == 3 and s["result"] is None
    assert "could not answer" in s["answer"]


def test_budget_stops(client):
    s = ask(graph(client, standin.FixtureSQLModel(usd=0.30)), COUNT, "t5")
    assert s["stop"] == "budget_usd" and s["result"] is None and model_calls(s) == 1


def test_decline(client):
    s = ask(graph(client, standin.FixtureSQLModel()), "Will Hotel Senior Lending cut its dividend?", "t6")
    assert s["query"]["sql"] is None and s["result"] is None and s["answer"] == standin.DECLINE


def test_follow_up_sees_history_and_new_thread_does_not(client):
    seen = []
    base = standin.FixtureSQLModel()

    def spy(req):
        seen.append(req)
        return base(req)
    app = graph(client, spy)
    ask(app, COUNT, "conv")
    ask(app, PIK, "conv")
    assert seen[-1]["history"][0]["question"] == COUNT
    ask(app, PIK, "other")
    assert seen[-1]["history"] == []


def test_record_then_two_replays_are_byte_identical(client):
    cache = TMP / "cache"
    rec = llm.ReplayClient(cache, "record", call=standin.FixtureSQLModel())
    traces = [json.dumps(ask(graph(client, rec), PIK, "r")["trace"], sort_keys=True)]
    for i in range(2):
        rep = llm.ReplayClient(cache, "replay")
        traces.append(json.dumps(ask(graph(client, rep), PIK, "r")["trace"], sort_keys=True))
    assert traces[0] == traces[1] == traces[2]
    with pytest.raises(llm.CacheMiss):
        ask(graph(client, llm.ReplayClient(cache, "replay")), "never recorded", "x")


# ------------------------------------------------------------ the real panel
REAL = ROOT / P["data"]["real_panel"]
ANTARES = "For Antares Strategic Credit Fund, how many current holdings fall under each investment type?"


@pytest.fixture(scope="module")
def real_client():
    if not REAL.exists():
        pytest.skip("no real panel")
    path = db.build_db(db.load_panel(REAL), TMP / "real.sqlite", (ROOT / "sql/holdings_v.sql").read_text())
    server.configure(db_path=path)
    c = PanelClient()
    yield c
    c.close()
    server.configure()


def test_schema_lists_exact_names_and_rules(real_client):
    seen = []
    model = standin.FixtureSQLModel(answers={ANTARES: [
        "SELECT investment_type, COUNT(*) FROM holdings_v WHERE bdc = 'ANTARES STRATEGIC CREDIT FUND' "
        "GROUP BY investment_type"]})
    ask(graph(real_client, lambda r: seen.append(r) or model(r)), ANTARES, "s1")
    schema = seen[0]["schema"]
    assert "ANTARES STRATEGIC CREDIT FUND; ANTARES STRATEGIC CREDIT FUND II LLC" in schema
    assert "- investment_type: DEBT; EQUITY; OTHER; UNKNOWN" in schema
    assert "Never use LIKE for a BDC name" in schema


def test_repair_on_the_real_panel(real_client):
    """A first query the server refuses (no such column), then the repaired one."""
    model = standin.FixtureSQLModel(answers={ANTARES: [
        "SELECT holding_type, COUNT(*) FROM holdings_v WHERE bdc = 'ANTARES STRATEGIC CREDIT FUND' "
        "GROUP BY holding_type",
        "SELECT investment_type, COUNT(*) AS n FROM holdings_v WHERE bdc = 'ANTARES STRATEGIC CREDIT FUND' "
        "GROUP BY investment_type ORDER BY investment_type"]})
    seen = []
    s = ask(graph(real_client, lambda r: seen.append(r) or model(r)), ANTARES, "s2")
    steps = [(t["node"], t.get("outcome")) for t in s["trace"]]
    assert steps == [("load_schema", None), ("generate", None), ("check", "ok"), ("execute", "invalid"),
                     ("generate", None), ("check", "ok"), ("execute", "ok"), ("summarize", None)]
    assert seen[1]["error"] == {"code": "invalid", "detail": "invalid: no such column: holding_type"}
    assert s["result"]["rows"] == [["DEBT", 1326], ["EQUITY", 92], ["UNKNOWN", 70]]
