"""Tests for the askpanel building blocks: python tests/run_tests.py (or pytest -q)."""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from askpanel import audit, catalog, check, clock, db, gate, llm, nodes, questions, standin, tools  # noqa: E402

PANEL = db.load_panel(ROOT / "data/fixture/panel_2p.csv")
TMP = Path(tempfile.mkdtemp())


_N = iter(range(10_000))


def _db(name="t.sqlite", view=None, extra=None):
    # a fresh file per call: Windows cannot delete a database another test still has open
    p = db.build_db(PANEL, TMP / f"{next(_N):03d}-{name}", view)
    if extra:
        con = sqlite3.connect(p); con.executescript(extra); con.commit(); con.close()
    return p


def _refused(con, sql, code):
    try:
        gate.run_query(con, sql)
    except gate.GateError as e:
        assert e.code == code, (sql, e.code, e.detail)
        return
    raise AssertionError(f"not refused: {sql}")


def _agent(model=None, **kw):
    led = audit.Ledger(clock=clock.clock)
    t = tools.local_tools(_db("agent.sqlite"), led, tables=("filings", "holdings"))
    n, rc, re_ = nodes.make_nodes(model or standin.FixtureSQLModel(), t, clock.clock,
                                  allowed={"filings", "holdings"}, **kw)
    return lambda q: nodes.run_plain(nodes.new_state(q), n, rc, re_), led


# ------------------------------------------------------------------ db
def test_build_db_tables():
    con = sqlite3.connect(_db())
    assert con.execute("SELECT COUNT(*) FROM filings").fetchone()[0] == 4
    assert con.execute("SELECT COUNT(*) FROM holdings").fetchone()[0] == len(PANEL) == 74


def test_build_db_rejects_inconsistent_filings():
    p = PANEL.copy(); p.loc[p.index[0], "name"] = "SOMETHING ELSE"
    try:
        db.build_db(p, TMP / "bad.sqlite")
    except ValueError as e:
        assert "disagree" in str(e); return
    raise AssertionError("inconsistent filings accepted")


def test_build_db_adds_missing_optional_columns():
    p = PANEL.drop(columns=["filed", "industry", "spread", "interest_rate"])
    con = sqlite3.connect(db.build_db(p, TMP / "thin.sqlite"))
    cols = {r[1] for r in con.execute("PRAGMA table_info(holdings)")}
    assert {"industry", "spread", "interest_rate"} <= cols
    assert "filed" in {r[1] for r in con.execute("PRAGMA table_info(filings)")}


def test_check_view_missing():
    assert db.check_view(_db(), PANEL) == ["no view named holdings_v"]


def test_check_view_catches_prior_rows_and_columns():
    v = "CREATE VIEW holdings_v AS SELECT h.adsh, f.name AS bdc FROM holdings h JOIN filings f USING (adsh);"
    probs = db.check_view(_db("v1.sqlite", v), PANEL)
    assert probs and all(x.startswith("missing column") for x in probs)


def test_check_view_catches_null_price_and_is_debt():
    v = """CREATE VIEW holdings_v AS
SELECT h.adsh, f.name AS bdc, f.form, f.period, h.identifier, h.investment_type, h.industry,
       h.fair_value, h.cost, h.principal, NULL AS price, h.pik_rate, h.interest_rate,
       h.spread, h.maturity, 0 AS is_debt
FROM holdings h JOIN filings f ON f.adsh = h.adsh WHERE h.period_role = 'current';"""
    probs = db.check_view(_db("v2.sqlite", v), PANEL)
    assert any("price" in x for x in probs) and any("is_debt" in x for x in probs)
    assert not any("row count" in x for x in probs)


def test_check_view_reference_solution():
    """Instructor only: skipped in the kit (the view is your work)."""
    ref = ROOT.parent / "lab4b-reference-solution" / "sql" / "holdings_v.sql"
    if ref.exists():
        assert db.check_view(_db("ref.sqlite", ref.read_text()), PANEL) == []


# ------------------------------------------------------------------ gate
def test_gate_allows_selects_and_ctes():
    con = gate.connect_ro(_db())
    r = gate.run_query(con, "SELECT f.name, COUNT(*) FROM holdings h JOIN filings f "
                            "ON f.adsh = h.adsh GROUP BY f.name")
    assert r["row_count"] == 4 and not r["truncated"]
    assert gate.run_query(con, "WITH x AS (SELECT * FROM holdings) SELECT COUNT(*) FROM x")["rows"] == [[74]]
    assert gate.run_query(con, "-- note\nSELECT 1;")["rows"] == [[1]]


def test_gate_refuses_writes_and_escapes():
    con = gate.connect_ro(_db())
    for sql, code in [("INSERT INTO filings VALUES (1,2,3,4,5,6)", "not_select"),
                      ("WITH x AS (SELECT 1) UPDATE filings SET name = 'x'", "not_authorized"),
                      ("DROP TABLE holdings", "not_select"),
                      ("ATTACH DATABASE 'x.db' AS x", "not_select"),
                      ("PRAGMA table_info(holdings)", "not_select"),
                      ("SELECT * FROM pragma_table_info('holdings')", "not_authorized"),
                      ("SELECT * FROM sqlite_master", "not_authorized"),
                      ("SELECT 1; DROP TABLE holdings", "multiple_statements"),
                      ("SELECT load_extension('x')", "not_authorized"),
                      ("   ;", "empty"),
                      ("SELECT fv FROM holdings", "invalid")]:
        _refused(con, sql, code)


def test_gate_refuses_tables_outside_the_list():
    con = gate.connect_ro(_db("secret.sqlite", extra="CREATE TABLE secret(x); INSERT INTO secret VALUES (1);"))
    _refused(con, "SELECT * FROM secret", "not_authorized")


def test_read_only_even_without_authorizer():
    con = gate.connect_ro(_db())
    con.set_authorizer(None)
    try:
        con.execute("INSERT INTO filings (adsh) VALUES ('x')")
    except sqlite3.OperationalError as e:
        assert "readonly" in str(e); return
    raise AssertionError("mode=ro did not hold")


def test_gate_timeout_and_row_cap():
    con = gate.connect_ro(_db())
    try:
        gate.run_query(con, "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) "
                            "SELECT MAX(x) FROM c", timeout_s=0.3)
    except gate.GateError as e:
        assert e.code == "timeout"
    else:
        raise AssertionError("no timeout")
    r = gate.run_query(con, "SELECT identifier FROM holdings", max_rows=10)
    assert r["row_count"] == 10 and r["truncated"]


def test_static_check():
    ok = ["SELECT * FROM holdings_v", "WITH x AS (SELECT * FROM holdings) SELECT * FROM x",
          "SELECT 'a;b' FROM filings", "SELECT * FROM holdings_v -- trailing; comment"]
    for s in ok:
        gate.static_check(s)
    for s, code in [("SELECT * FROM sqlite_master", "not_authorized"),
                    ("SELECT 1; SELECT 2", "multiple_statements"),
                    ("DELETE FROM holdings", "not_select"),
                    ("SELECT * FROM filings f JOIN secret s ON 1", "not_authorized"),
                    ("WITH x AS (SELECT 1) DELETE FROM holdings", "not_select"),
                    ("", "empty")]:
        try:
            gate.static_check(s)
        except gate.GateError as e:
            assert e.code == code, (s, e.code)
        else:
            raise AssertionError(s)


# ------------------------------------------------------------------ catalog and tools
def test_catalog_conformance():
    assert catalog.conformance(dict(catalog.CATALOG)) == []
    mine = dict(catalog.CATALOG); mine.pop("sample_values"); mine["drop_table"] = "DESTRUCTIVE"
    assert len(catalog.conformance(mine)) == 2


def test_tools_and_ledger():
    led = audit.Ledger(clock=clock.clock)
    t = tools.local_tools(_db(), led, tables=("filings", "holdings"))
    assert t["list_tables"]() == ["filings", "holdings"]
    assert {c["column"] for c in t["describe_table"](table="filings")} >= {"adsh", "name"}
    assert len(t["sample_values"](table="filings", column="name")) == 4
    try:
        t["run_query"](sql="DROP TABLE holdings")
    except gate.GateError:
        pass
    assert led.find("policy_block", tool="run_query", code="not_select")
    try:
        t["describe_table"](table="sqlite_master")
    except gate.GateError as e:
        assert e.code == "not_authorized"
    else:
        raise AssertionError("unknown table described")


# ------------------------------------------------------------------ replay
def test_replay_client():
    d = TMP / "cache"
    try:
        llm.ReplayClient(d)({"q": 1})
    except llm.CacheMiss:
        pass
    else:
        raise AssertionError("no cache miss")
    calls = []
    rec = llm.ReplayClient(d, "record", call=lambda r: calls.append(1) or {"sql": "SELECT 1"})
    assert rec({"q": 1}) == llm.ReplayClient(d)({"q": 1}) == {"sql": "SELECT 1"} and len(calls) == 1


# ------------------------------------------------------------------ nodes
def test_agent_answers_repairs_and_declines():
    ask, led = _agent()
    s = ask("Which BDC has the largest total fair value in its current schedule?")
    assert "GOLF" in s["answer"] and [t["node"] for t in s["trace"]] == \
        ["load_schema", "generate", "check", "execute", "summarize"]
    s = ask("Which current debt holdings carry a PIK rate above 2%?")
    assert sum(t["node"] == "generate" for t in s["trace"]) == 2 and s["result"]["row_count"] == 2
    s = ask("What will next quarter's NAV be?")
    assert s["query"]["sql"] is None and s["answer"] == standin.DECLINE and s["result"] is None


def test_agent_repairs_a_reply_with_neither_sql_nor_decline():
    class Empty:
        def __call__(self, req):
            return {"sql": None, "decline": None, "usd": 0.001, "tokens_in": 10, "tokens_out": 5}
    ask, _ = _agent(Empty(), max_attempts=2)
    s = ask("anything")
    assert [t.get("outcome") for t in s["trace"] if t["node"] == "check"] == ["invalid", "invalid"]
    assert s["answer"].startswith("I could not answer that: invalid")


def test_answer_formatting():
    r = {"columns": ["bdc", "price", "pik_rate", "fv"], "rows": [["A", 89.5, 0.0955, 14000000.0]],
         "row_count": 1, "truncated": False}
    assert nodes.format_answer(r).splitlines()[2] == "A | 89.5 | 0.0955 | 14,000,000.00"


def test_agent_stops_after_max_attempts():
    bad = standin.FixtureSQLModel({"q": ["SELECT nope FROM holdings"]})
    ask, _ = _agent(bad, max_attempts=3)
    s = ask("q")
    assert sum(t["node"] == "generate" for t in s["trace"]) == 3
    assert s["answer"].startswith("I could not answer that: invalid")


def test_agent_budget_guard():
    pricey = standin.FixtureSQLModel(usd=0.30)
    ask, _ = _agent(pricey, usd_cap=0.10)
    s = ask("How many current holdings does each BDC report?")
    assert s["stop"] == "budget_usd" and s["result"] is None and "Stopped" in s["answer"]


def test_traces_are_deterministic():
    ask, _ = _agent()
    q = "Which current debt holdings carry a PIK rate above 2%?"
    assert json.dumps(ask(q)["trace"]) == json.dumps(ask(q)["trace"])
    assert all("request_key" in t for t in ask(q)["trace"] if t["node"] == "generate")


# ------------------------------------------------------------------ questions and self-check
def test_question_coverage():
    assert questions.validate(questions.load(ROOT / "questions/questions.example.yaml"))
    good = [{"id": f"q{i}", "category": c, "question": "x"} for i, c in enumerate(
        ["lookup", "lookup", "aggregation", "aggregation", "cross_bdc", "cross_bdc",
         "over_time", "over_time", "follow_up", "decline"])]
    good[8]["follows"] = "q7"
    assert questions.validate(good) == []


def test_self_check_contract_and_failures():
    c = TMP / "contract.py"
    c.write_text("class SchemaCatalog: pass\nclass QueryRequest: pass\nclass SQLQuery: pass\n"
                 "class QueryResult: pass\ndef validate_query(q): return q\n")
    assert check.CONTRACT == check.contract_names(c)
    template = (ROOT / "outputs/failures.example.md").read_text()
    assert check.failure_entries(template) == 0
    filled = "# Log\n" + "".join(f"## F{i}\nQuestion: q\nWhat went wrong: x\nWhat fixed it: a view\n"
                                   for i in range(3))
    assert check.failure_entries(filled) == 3


def test_self_check_helpers():
    srv = TMP / "server.py"
    srv.write_text('REGISTRY = {"list_tables": "READ", "describe_table": "READ", '
                   '"sample_values": "READ", "run_query": "READ"}\n')
    assert catalog.conformance(check.registry_from(srv)) == []
    a = TMP / "agent.py"
    a.write_text("import sqlite3\nX = 'data/panel.sqlite'\n")
    assert len(check.direct_db_access([a])) == 2
    g = TMP / "graph.py"
    g.write_text("g = StateGraph(S)\nfor n in ['load_schema','generate','check','execute','summarize']: pass\n"
                 "g.add_node('load_schema', f)\ng.add_node('generate', f)\ng.add_node('check', f)\n"
                 "g.add_node('execute', f)\ng.add_node('summarize', f)\n"
                 "g.add_conditional_edges('check', r)\ng.add_conditional_edges('execute', r)\n"
                 "app = g.compile(checkpointer=InMemorySaver())\n")
    assert check.graph_shape(g) == []


def test_self_check_on_bare_kit():
    """Runs on a fresh copy of the kit, so it still passes once you add your work."""
    import shutil
    bare = TMP / "bare"
    shutil.rmtree(bare, ignore_errors=True)
    for d in ("src", "data/fixture", "questions", "outputs"):
        shutil.copytree(ROOT / d, bare / d, ignore=shutil.ignore_patterns(
            "questions.yaml", "economics.md", "failures.md", "q*.json", "*.sqlite", "cache"))
    shutil.copy(ROOT / "params.yaml", bare / "params.yaml")
    res = check.run_checks(bare)
    assert len(res) == 12 and not any(ok for _, ok, _ in res), [r for r in res if r[1]]
