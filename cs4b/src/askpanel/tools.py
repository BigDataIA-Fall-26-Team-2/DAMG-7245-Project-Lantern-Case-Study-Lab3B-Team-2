"""Plain-Python versions of the four catalog tools, over a read-only
connection, with an audit event per call. The notebooks use them; your MCP
server (Lab 34B) wraps them, adds Pydantic schemas and contract tests.
Wrap them; do not bypass the gate."""
from . import gate

DESCRIPTIONS = {   # what the model reads about each column of holdings_v
    "adsh": "SEC accession number of the filing (cite it)",
    "bdc": "BDC name exactly as the SEC data set spells it",
    "form": "10-K or 10-Q",
    "period": "the filing's period end date, YYYY-MM-DD",
    "identifier": "the holding as the BDC describes it (borrower | instrument | terms)",
    "investment_type": "e.g. First Lien Senior Secured Debt [Member], Equity Securities [Member]",
    "industry": "the BDC's industry label for the borrower",
    "fair_value": "fair value in US dollars",
    "cost": "amortized cost in US dollars",
    "principal": "principal in US dollars; NULL for equity",
    "price": "100 * fair_value / principal; NULL for equity",
    "pik_rate": "paid-in-kind rate as a decimal (0.02 = 2%); NULL if none",
    "interest_rate": "all-in interest rate as a decimal",
    "spread": "spread over the base rate as a decimal",
    "maturity": "maturity date, YYYY-MM-DD",
    "is_debt": "1 for debt (has principal), 0 for equity",
    # base tables (filings, holdings)
    "cik": "SEC central index key of the BDC",
    "name": "BDC name exactly as the SEC data set spells it",
    "filed": "date the filing was filed, YYYY-MM-DD",
    "period_role": "'current' (this period's schedule) or 'prior' (the prior fiscal year-end's)",
    "ddate": "the date of the schedule this row belongs to, YYYY-MM-DD",
    "pct_net_assets": "the holding as a share of net assets, as a decimal",
    "source_rows": "row numbers in the SEC data set this holding came from",
}


def local_tools(db_path, ledger, max_rows=200, timeout_s=5.0,
                tables=("holdings_v", "filings", "holdings")):
    con = gate.connect_ro(db_path, tables=set(tables))

    def _cols(table):
        if table not in tables:
            raise gate.GateError("not_authorized", f"unknown table {table!r}")
        cur = con.execute(f'SELECT * FROM "{table}" LIMIT 0')
        return [d[0] for d in cur.description]

    def list_tables():
        ledger.record("tool_call", tool="list_tables")
        return list(tables)

    def describe_table(table: str):
        cols = _cols(table)
        ledger.record("tool_call", tool="describe_table", table=table)
        return [{"column": c, "description": DESCRIPTIONS.get(c, "")} for c in cols]

    def sample_values(table: str, column: str, limit: int = 20):
        if column not in _cols(table):
            raise gate.GateError("invalid", f"no column {column!r} in {table}")
        r = gate.run_query(con, f'SELECT DISTINCT "{column}" FROM "{table}" '
                                f'WHERE "{column}" IS NOT NULL ORDER BY 1 LIMIT {int(limit)}')
        ledger.record("tool_call", tool="sample_values", table=table, column=column)
        return [row[0] for row in r["rows"]]

    def run_query(sql: str):
        try:
            r = gate.run_query(con, sql, max_rows=max_rows, timeout_s=timeout_s)
        except gate.GateError as e:
            ledger.record("policy_block", tool="run_query", code=e.code)
            raise
        ledger.record("tool_call", tool="run_query", rows=r["row_count"],
                      truncated=r["truncated"], ms=r["ms"])
        return r

    return {"list_tables": list_tables, "describe_table": describe_table,
            "sample_values": sample_values, "run_query": run_query}
