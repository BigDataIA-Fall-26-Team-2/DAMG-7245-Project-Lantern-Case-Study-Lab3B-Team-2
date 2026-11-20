"""The HTTP API, in replay mode (no key, no network).

    cd cs4b && pytest -q api/tests
"""
import json
import re
from pathlib import Path

import pytest

CS4B = Path(__file__).resolve().parents[2]
SAVED = {p.stem: json.loads(p.read_text()) for p in (CS4B / "outputs/questions").glob("q*.json")}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    h = r.json()
    assert h["status"] == "ok" and h["default_mode"] == "replay"
    assert h["modes"]["replay"] == {"available": True, "reason": None}
    assert h["modes"]["live"]["available"] is False and "GEMINI_API_KEY" in h["modes"]["live"]["reason"]
    assert sorted(h["tools"]) == ["describe_table", "list_tables", "run_query", "sample_values"]
    assert h["recorded_questions"] == 10 and h["cached_responses"] >= 10


def test_questions(client):
    qs = client.get("/questions").json()
    assert [q["id"] for q in qs] == [f"q{i:02d}" for i in range(1, 11)]
    assert next(q for q in qs if q["id"] == "q03")["follows"] == "q02"


def test_schema_comes_from_mcp(client):
    s = client.get("/schema").json()
    tables = {t["table"]: {c["column"]: c["description"] for c in t["columns"]} for t in s["tables"]}
    assert set(tables) == {"holdings_v", "filings", "holdings"}
    assert "NOT a debt/equity label" in tables["holdings_v"]["is_debt"]   # the server's own text


@pytest.mark.parametrize("qid", ["q01", "q04", "q06", "q09"])
def test_ask_matches_saved_answer(client, recorded, qid):
    r = client.post("/ask", json={"question": recorded[qid]["question"]})
    assert r.status_code == 200, r.text
    a, saved = r.json(), SAVED[qid]
    assert a["sql"] == saved["sql"] and a["answer"] == saved["answer"]
    assert a["rows"] == saved["result"]["rows"] and a["columns"] == saved["result"]["columns"]
    assert a["usd"] == pytest.approx(saved["usd"]) and a["model_calls"] == 1 and a["attempts"] == 0
    assert not a["declined"] and a["turn"] == 1 and a["thread_id"].startswith("c-")
    assert a["mode"] == "replay" and a["thread_reset"] is False and a["fresh_model_calls"] == 0
    assert [t["node"] for t in a["trace"]] == ["load_schema", "generate", "check", "execute", "summarize"]


def test_decline(client, recorded):
    a = client.post("/ask", json={"question": recorded["q10"]["question"]}).json()
    assert a["declined"] and a["sql"] is None and a["rows"] == []
    assert a["decline_reason"] == SAVED["q10"]["decline"] == a["answer"]
    assert "execute" not in [t["node"] for t in a["trace"]]


def test_follow_up_keeps_the_thread(client, recorded):
    tid = client.post("/conversations").json()["thread_id"]
    assert client.get(f"/conversations/{tid}").json() == {"thread_id": tid, "mode": "replay", "turns": []}
    a1 = client.post("/ask", json={"question": recorded["q02"]["question"], "thread_id": tid}).json()
    a2 = client.post("/ask", json={"question": recorded["q03"]["question"], "thread_id": tid}).json()
    assert a1["row_count"] == 15 and a2["turn"] == 2 and a2["thread_id"] == tid
    assert a2["rows"] == [[106150000.0]]
    h = client.get(f"/conversations/{tid}").json()
    assert [t["question"] for t in h["turns"]] == [recorded["q02"]["question"], recorded["q03"]["question"]]
    assert h["turns"][1]["sql"] == SAVED["q03"]["sql"]


def test_follow_up_on_a_new_thread_is_a_cache_miss(client, recorded):
    r = client.post("/ask", json={"question": recorded["q03"]["question"]})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "cache_miss"
    assert "isn't in the replay cache" in r.json()["detail"]["message"]


def test_unrecorded_question_is_409(client):
    r = client.post("/ask", json={"question": "What is the meaning of life?"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cache_miss"


@pytest.mark.parametrize("body", [{}, {"question": ""}, {"question": "   "},
                                  {"question": "x", "thread_id": "bad id!"}])
def test_bad_requests_are_422(client, body):
    assert client.post("/ask", json=body).status_code == 422


def test_unknown_conversation_is_404(client):
    r = client.get("/conversations/c-doesnotexist")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "unknown_thread"


def test_economics(client):
    e = client.get("/economics").json()
    assert [l["line"] for l in e["lines"]] == ["Cost per completed task", "Latency", "Human time saved",
                                               "Quality", "Cost of failure"]
    c = e["computed"]
    assert c["questions"] == 10 and c["usd_total"] == pytest.approx(0.009072, abs=1e-6)
    assert c["model_calls_per_question"] == 1.0 and c["no_sql"] == 1
    assert [round(h["usd"]) for h in c["hours_saved"]] == [200, 400, 800]


def test_cors_allows_the_vite_dev_server(client):
    r = client.options("/ask", headers={"Origin": "http://localhost:5173",
                                        "Access-Control-Request-Method": "POST",
                                        "Access-Control-Request-Headers": "content-type"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_openapi_documents_every_endpoint(client):
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    for p, m in [("/health", "get"), ("/questions", "get"), ("/ask", "post"), ("/conversations", "post"),
                 ("/conversations/{thread_id}", "get"), ("/schema", "get"), ("/economics", "get")]:
        op = paths[p][m]
        ok = op["responses"].get("200") or op["responses"].get("201")
        assert "$ref" in json.dumps(ok), f"{m.upper()} {p} has no response model"
    assert "409" in paths["/ask"]["post"]["responses"]
    assert "example" in json.dumps(spec["components"]["schemas"]["AskResponse"])


def test_repair_is_visible_in_the_trace():
    """A stand-in model whose first SQL the server refuses: the trace shows the repair."""
    from api.service import PanelService
    from askpanel import standin
    q = "How many current holdings per investment type at Antares Strategic Credit Fund?"
    model = standin.FixtureSQLModel(answers={q: [
        "SELECT holding_type, COUNT(*) FROM holdings_v WHERE bdc = 'ANTARES STRATEGIC CREDIT FUND' "
        "GROUP BY holding_type",
        "SELECT investment_type, COUNT(*) AS n FROM holdings_v WHERE bdc = 'ANTARES STRATEGIC CREDIT FUND' "
        "GROUP BY investment_type ORDER BY investment_type"]})
    svc = PanelService(replay_model=model, model_name="stand-in")
    try:
        a = svc.ask(q)
    finally:
        svc.close()
    steps = [(t["node"], t.get("outcome")) for t in a["trace"]]
    assert ("execute", "invalid") in steps and steps[-2] == ("execute", "ok")
    assert a["attempts"] == 1 and a["model_calls"] == 2
    assert a["rows"] == [["DEBT", 1326], ["EQUITY", 92], ["UNKNOWN", 70]]


NO_DB = re.compile(r"^\s*(import|from)\s+(sqlite3|duckdb|sqlalchemy|apsw)\b|panel\.sqlite|\.sqlite\b", re.M)


def test_api_and_frontend_never_touch_the_database():
    files = [p for d in ("api", "frontend") for p in (CS4B / d).rglob("*")
             if p.is_file() and p.suffix in {".py", ".ts", ".tsx", ".js", ".json"}
             and "node_modules" not in p.parts and "dist" not in p.parts
             and "tests" not in p.relative_to(CS4B).parts]     # conftest builds the DB via tools/
    assert files
    hits = [str(p.relative_to(CS4B)) for p in files if NO_DB.search(p.read_text(encoding="utf-8"))]
    assert hits == []
