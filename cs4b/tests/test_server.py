"""Part 2 (Lab 34B): the MCP query server, over the protocol (in-memory Client).

    pytest -q tests/test_server.py

Runs on a scratch copy of the fixture database (with our holdings_v), so it needs
no API key and does not depend on which panel params.yaml selects.
"""
import asyncio
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from mcp import Client  # noqa: E402

from askpanel import catalog, db  # noqa: E402
from services.mcp import server  # noqa: E402

TMP = Path(tempfile.mkdtemp())
DB = db.build_db(db.load_panel(ROOT / "data/fixture/panel_2p.csv"), TMP / "server.sqlite",
                 (ROOT / "sql/holdings_v.sql").read_text())


@pytest.fixture(autouse=True)
def fresh_server():
    led = server.configure(db_path=DB)
    yield led
    server.configure()          # close the connection (Windows keeps open files locked)


def call(tool, args=None):
    async def go():
        async with Client(server.mcp) as c:
            return await c.call_tool(tool, args or {})
    return asyncio.run(go())


def tools_listed():
    async def go():
        async with Client(server.mcp) as c:
            return (await c.list_tools()).tools
    return asyncio.run(go())


def refused(sql):
    r = call("run_query", {"sql": sql})
    assert r.is_error, f"not refused: {sql}"
    return r.content[0].text


# ------------------------------------------------------------ the catalog
def test_catalog_is_closed():
    names = {t.name for t in tools_listed()}
    assert names == set(catalog.CATALOG) == set(server.REGISTRY)
    assert catalog.conformance(server.REGISTRY) == []


def test_every_tool_is_read_only_with_an_output_schema():
    for t in tools_listed():
        assert t.annotations.read_only_hint is True, t.name
        assert t.output_schema is not None, t.name


def test_unknown_tool_is_an_error():
    assert call("export_panel").is_error


# ------------------------------------------------------------ reads work
def test_list_and_describe():
    assert call("list_tables").structured_content["tables"] == ["holdings_v", "filings", "holdings"]
    cols = call("describe_table", {"table": "holdings_v"}).structured_content["columns"]
    assert [c["column"] for c in cols] == db.VIEW_COLUMNS
    assert all(c["description"] for c in cols)


def test_sample_values():
    r = call("sample_values", {"table": "holdings_v", "column": "bdc"})
    assert not r.is_error and len(r.structured_content["values"]) == 4


def test_select_works():
    r = call("run_query", {"sql": "SELECT bdc, COUNT(*) AS n FROM holdings_v GROUP BY bdc ORDER BY bdc"})
    assert not r.is_error
    s = r.structured_content
    assert s["columns"] == ["bdc", "n"] and s["row_count"] == 4
    assert sum(row[1] for row in s["rows"]) == 37          # 37 current holdings in the fixture


def test_row_cap():
    r = call("run_query", {"sql": "SELECT * FROM holdings h1, holdings h2"}).structured_content
    assert r["row_count"] == server.MAX_ROWS and r["truncated"] is True


# ------------------------------------------------------------ refusals
def test_insert_refused():
    assert "not_select" in refused("INSERT INTO filings (adsh) VALUES ('x')")


def test_drop_refused():
    assert "not_select" in refused("DROP TABLE holdings")


def test_attach_refused():
    refused("ATTACH DATABASE 'other.sqlite' AS o")


def test_pragma_refused():
    refused("PRAGMA table_info(holdings)")
    refused("SELECT * FROM pragma_table_info('holdings')")     # passes a keyword filter; the authorizer refuses


def test_sqlite_master_refused():
    assert "not_authorized" in refused("SELECT * FROM sqlite_master")


def test_second_statement_after_semicolon_refused():
    assert "multiple_statements" in refused("SELECT 1; DROP TABLE holdings")
    assert "multiple_statements" in refused("SELECT * FROM filings; DELETE FROM filings")


def test_write_in_cte_and_unknown_table_refused():
    refused("WITH x AS (SELECT 1) UPDATE filings SET name = 'x'")
    assert call("describe_table", {"table": "sqlite_master"}).is_error
    assert call("sample_values", {"table": "holdings_v", "column": "nope"}).is_error


def test_database_unchanged_after_refusals():
    for s in ["DELETE FROM holdings", "DROP TABLE filings", "SELECT 1; DELETE FROM holdings"]:
        refused(s)
    assert call("run_query", {"sql": "SELECT COUNT(*) FROM holdings"}).structured_content["rows"] == [[74]]


# ------------------------------------------------------------ the ledger
def test_ledger_records_calls_and_refusals(fresh_server):
    call("list_tables")
    call("run_query", {"sql": "SELECT COUNT(*) FROM holdings_v"})
    refused("DROP TABLE holdings")
    kinds = [(e["kind"], e["tool"]) for e in fresh_server.events]
    assert kinds == [("tool_call", "list_tables"), ("tool_call", "run_query"),
                     ("policy_block", "run_query")]
    block = fresh_server.events[-1]
    assert block["code"] == "not_select" and "sql_hash" in block
    assert "DROP" not in str(block)                          # hashes, never the client's text


def test_configure_restores_default_database(monkeypatch, tmp_path):
    """Fixture DB selection must not leak into a subsequent API/application run."""
    default = tmp_path / "default.sqlite"
    monkeypatch.setenv("ASKPANEL_DB", str(default))
    try:
        server.configure(db_path=tmp_path / "fixture.sqlite")
        server.configure()
        assert server._State.db_path == default
    finally:
        monkeypatch.delenv("ASKPANEL_DB")
        server.configure()
