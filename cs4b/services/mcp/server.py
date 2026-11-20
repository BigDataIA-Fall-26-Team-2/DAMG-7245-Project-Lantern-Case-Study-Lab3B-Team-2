"""The Ask the Panel query server (Lab 34B): MCP Python SDK v2, four READ tools.

    mcp dev services/mcp/server.py          # the Inspector
    python services/mcp/server.py           # stdio

The catalog is closed: exactly list_tables, describe_table, sample_values and
run_query, all READ. The database is opened read-only with the kit's authorizer
(gate.connect_ro); every query goes through gate.run_query (one statement,
SELECT only, row cap, timeout). Every call and every refusal is a ledger event.
"""
import hashlib
import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from mcp.server import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from askpanel import audit, clock, gate, tools  # noqa: E402

# The closed catalog, as a literal (the self-check reads it).
REGISTRY = {
    "list_tables": "READ",
    "describe_table": "READ",
    "sample_values": "READ",
    "run_query": "READ",
}

P = yaml.safe_load((ROOT / "params.yaml").read_text())
TABLES = tuple(P["server"]["tables"])
MAX_ROWS = int(P["server"]["max_rows"])
TIMEOUT_S = float(P["server"]["timeout_s"])
# What the model reads about each column: the kit's descriptions, corrected where our
# Lab 3B panel differs (failure 2 in outputs/failures.md).
DESCRIPTIONS = {
    **tools.DESCRIPTIONS,
    "investment_type": "the holding's type: DEBT, EQUITY, UNKNOWN (not tagged in the filing) "
                       "or OTHER; the exact values are listed below",
    "is_debt": "1 where a principal is reported (principal > 0, so price is defined), else 0; "
               "NOT a debt/equity label: some DEBT rows report no principal and a few EQUITY "
               "rows report one; use investment_type for debt versus equity",
    "industry": "the BDC's industry label for the borrower (NULL when the filing gives none)",
}
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                       openWorldHint=False)


# ------------------------------------------------------------ output models
class TableList(BaseModel):
    tables: list[str]


class Column(BaseModel):
    column: str
    description: str = ""


class TableDescription(BaseModel):
    table: str
    columns: list[Column]


class SampleValues(BaseModel):
    table: str
    column: str
    values: list[Any]


class QueryResult(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    ms: float


# ------------------------------------------------------------ state
class _State:
    db_path: Path = Path(os.environ.get("ASKPANEL_DB") or ROOT / P["data"]["db"])
    con = None
    lock = threading.Lock()
    ledger = None


def _ledger_file():
    f = P["server"].get("ledger")
    if not f:
        return None
    f = ROOT / f
    f.parent.mkdir(parents=True, exist_ok=True)
    return f


def configure(db_path=None, ledger_path=None):
    """Point the server at a database (tests use a scratch copy) and an
    optional JSONL ledger file. Closes any open connection."""
    with _State.lock:
        if _State.con is not None:
            _State.con.close()
            _State.con = None
        if db_path is not None:
            _State.db_path = Path(db_path)
        _State.ledger = audit.Ledger(path=ledger_path, clock=clock.clock)
    return _State.ledger


def ledger():
    return _State.ledger


configure(ledger_path=_ledger_file())


def _con():
    if _State.con is None:
        _State.con = gate.connect_ro(_State.db_path, tables=set(TABLES))   # mode=ro + authorizer
    return _State.con


def _h(text):
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _refuse(tool, code, detail, **fields):
    _State.ledger.record("policy_block", tool=tool, code=code, **fields)
    raise ToolError(f"{code}: {detail}")


def _columns(tool, table):
    if table not in TABLES:
        _refuse(tool, "not_authorized", f"unknown table {table!r}; the catalog is {list(TABLES)}",
                table=table)
    cur = _con().execute(f'SELECT * FROM "{table}" LIMIT 0')
    return [d[0] for d in cur.description]


mcp = MCPServer("askpanel-query", instructions=(
    "Read-only SQL over the Lab 3B BDC holdings panel. Call list_tables and "
    "describe_table first; run_query runs ONE SELECT and nothing else."))


@mcp.tool(annotations=READ)
def list_tables() -> TableList:
    """List the tables and views you may query (READ)."""
    with _State.lock:
        _State.ledger.record("tool_call", tool="list_tables")
        return TableList(tables=list(TABLES))


@mcp.tool(annotations=READ)
def describe_table(table: str) -> TableDescription:
    """The columns of one table or view, each with what it means (READ)."""
    with _State.lock:
        cols = _columns("describe_table", table)
        _State.ledger.record("tool_call", tool="describe_table", table=table)
        return TableDescription(table=table, columns=[
            Column(column=c, description=DESCRIPTIONS.get(c, "")) for c in cols])


@mcp.tool(annotations=READ)
def sample_values(table: str, column: str, limit: int = 20) -> SampleValues:
    """Up to `limit` distinct non-null values of one column, sorted (READ).
    Use it to spell BDC names and investment types exactly."""
    with _State.lock:
        if column not in _columns("sample_values", table):
            _refuse("sample_values", "invalid", f"no column {column!r} in {table}",
                    table=table, column=column)
        n = max(1, min(int(limit), MAX_ROWS))
        try:
            r = gate.run_query(_con(), f'SELECT DISTINCT "{column}" FROM "{table}" '
                                       f'WHERE "{column}" IS NOT NULL ORDER BY 1 LIMIT {n}',
                               max_rows=MAX_ROWS, timeout_s=TIMEOUT_S)
        except gate.GateError as e:
            _refuse("sample_values", e.code, e.detail, table=table, column=column)
        _State.ledger.record("tool_call", tool="sample_values", table=table, column=column,
                             rows=r["row_count"])
        return SampleValues(table=table, column=column, values=[row[0] for row in r["rows"]])


@mcp.tool(annotations=READ)
def run_query(sql: str) -> QueryResult:
    """Run ONE read-only SELECT (or WITH ... SELECT) over the catalog tables (READ).
    Refused: writes, ATTACH, PRAGMA, sqlite_master, more than one statement.
    At most server.max_rows rows; stopped after server.timeout_s seconds."""
    with _State.lock:
        try:
            r = gate.run_query(_con(), sql, max_rows=MAX_ROWS, timeout_s=TIMEOUT_S)
        except gate.GateError as e:
            _refuse("run_query", e.code, e.detail, sql_hash=_h(sql or ""))
        _State.ledger.record("tool_call", tool="run_query", sql_hash=_h(r["sql"]),
                             rows=r["row_count"], truncated=r["truncated"], ms=r["ms"])
        return QueryResult(**r)


def serve(transport: Optional[str] = None):
    mcp.run(transport or "stdio")


if __name__ == "__main__":
    serve()
