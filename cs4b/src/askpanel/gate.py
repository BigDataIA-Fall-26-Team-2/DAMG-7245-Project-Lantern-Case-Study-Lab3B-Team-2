"""The SQL gate. Read-only by construction, not by keyword filtering:

1. the database is opened with mode=ro, so SQLite itself refuses writes;
2. an authorizer allows only SELECT and reads of named tables, so ATTACH,
   PRAGMA, sqlite_master and every write are refused when the SQL compiles;
3. one statement only, and it must start with SELECT or WITH;
4. a row cap and a wall-clock timeout on every query.
"""
import re
import sqlite3
import time
from pathlib import Path

ALLOWED_TABLES = frozenset({"holdings_v", "holdings", "filings"})
_OK, _DENY = sqlite3.SQLITE_OK, sqlite3.SQLITE_DENY
_ALLOW_ACTIONS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION,
                  getattr(sqlite3, "SQLITE_RECURSIVE", 33)}
_COMMENTS = re.compile(r"(--[^\n]*\n?)|(/\*.*?\*/)", re.S)


class GateError(ValueError):
    """A refused query. code: empty, not_select, multiple_statements,
    not_authorized, invalid, timeout."""

    def __init__(self, code, detail):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def _authorizer(tables):
    def auth(action, arg1, arg2, dbname, inner):
        if action in _ALLOW_ACTIONS:
            return _OK
        if action == sqlite3.SQLITE_READ and arg1 in tables:
            return _OK
        return _DENY
    return auth


def connect_ro(db_path, tables=ALLOWED_TABLES):
    """A read-only connection with the authorizer installed."""
    p = Path(db_path).resolve()
    if not p.exists():
        raise FileNotFoundError(p)
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, check_same_thread=False)
    con.set_authorizer(_authorizer(set(tables)))
    return con


def check_sql(con, sql):
    """Return the SQL ready to run, or raise GateError. Compiles it (EXPLAIN)
    under the authorizer, so nothing executes."""
    s = (sql or "").strip().rstrip(";").strip()
    if not s:
        raise GateError("empty", "no SQL")
    head = _COMMENTS.sub(" ", s).strip().split(None, 1)
    if not head or head[0].upper() not in {"SELECT", "WITH"}:
        raise GateError("not_select", "only SELECT (or WITH ... SELECT) is allowed")
    try:
        con.execute("EXPLAIN " + s).fetchall()
    except sqlite3.ProgrammingError as e:
        raise GateError("multiple_statements", str(e)) from None
    except sqlite3.DatabaseError as e:
        msg = str(e)
        if "not authorized" in msg or "prohibited" in msg:
            raise GateError("not_authorized", msg) from None
        raise GateError("invalid", msg) from None
    return s


def run_query(con, sql, max_rows=200, timeout_s=5.0):
    """Gate, run and cap one query. Returns a JSON-ready dict."""
    s = check_sql(con, sql)
    deadline = time.monotonic() + timeout_s
    con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
    t0 = time.perf_counter()
    try:
        cur = con.execute(s)
        rows = cur.fetchmany(max_rows + 1)
    except sqlite3.OperationalError as e:
        if "interrupted" in str(e):
            raise GateError("timeout", f"over {timeout_s:g}s") from None
        if "not authorized" in str(e):
            raise GateError("not_authorized", str(e)) from None
        raise GateError("invalid", str(e)) from None
    finally:
        con.set_progress_handler(None, 0)
    cols = [d[0] for d in cur.description or []]
    return {"sql": s, "columns": cols,
            "rows": [list(r) for r in rows[:max_rows]],
            "row_count": min(len(rows), max_rows),
            "truncated": len(rows) > max_rows,
            "ms": round(1000 * (time.perf_counter() - t0), 1)}


_STRINGS = re.compile(r"'(?:[^']|'')*'")
_TABLE_REF = re.compile(r'\b(?:FROM|JOIN)\s+"?([A-Za-z_][A-Za-z0-9_]*)"?', re.I)
_WRITE_WORDS = re.compile(r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|ATTACH|DETACH|"
                          r"PRAGMA|VACUUM|REINDEX)\b|\bREPLACE\s+INTO\b", re.I)
_CTE_NAME = re.compile(r'(?:\bWITH(?:\s+RECURSIVE)?|,)\s*"?([A-Za-z_][A-Za-z0-9_]*)"?\s*'
                       r'(?:\([^)]*\)\s*)?AS\s*\(', re.I)


def static_check(sql, allowed=ALLOWED_TABLES):
    """The checks that need no database: what the agent's Pydantic validator
    runs before calling the server. The server's run_query is still the
    authority (it compiles under the authorizer). Returns the cleaned SQL or
    raises GateError."""
    s = (sql or "").strip().rstrip(";").strip()
    if not s:
        raise GateError("empty", "no SQL")
    bare = _COMMENTS.sub(" ", _STRINGS.sub("''", s))
    head = bare.strip().split(None, 1)
    if not head or head[0].upper() not in {"SELECT", "WITH"}:
        raise GateError("not_select", "only SELECT (or WITH ... SELECT) is allowed")
    bare_kw = re.sub(r'"(?:[^"]|"")*"', '""', bare)   # quoted names hide no keywords
    if ";" in bare_kw:
        raise GateError("multiple_statements", "one statement only")
    w = _WRITE_WORDS.search(bare_kw)
    if w:
        raise GateError("not_select", f"{w.group(0).upper()} is not allowed in a read-only query")
    ctes = {m.lower() for m in _CTE_NAME.findall(bare)}
    used = {t.lower() for t in _TABLE_REF.findall(bare)} - ctes
    bad = sorted(used - {a.lower() for a in allowed})
    if bad:
        raise GateError("not_authorized", f"tables not in the catalog: {bad}")
    return s
