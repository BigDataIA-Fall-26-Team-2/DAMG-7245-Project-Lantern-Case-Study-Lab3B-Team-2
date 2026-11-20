"""Part 1 (Lab 33B): the Pydantic contract. pytest -q tests/test_contract.py"""
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.contract import (QueryRequest, QueryResult, SchemaCatalog,  # noqa: E402
                            SQLQuery, validate_query)


def _code(data):
    model, err = validate_query(data)
    assert model is None, data
    return err["code"]


def test_select_passes_and_is_cleaned():
    model, err = validate_query({"sql": "SELECT bdc FROM holdings_v;", "explanation": "x"})
    assert err is None and model.sql == "SELECT bdc FROM holdings_v"


def test_decline_passes():
    model, err = validate_query({"sql": None, "decline": "not in the panel"})
    assert err is None and model.decline == "not in the panel"


def test_delete_refused():
    assert _code({"sql": "DELETE FROM holdings"}) == "not_select"


def test_two_statements_refused():
    assert _code({"sql": "SELECT 1; DROP TABLE holdings"}) == "multiple_statements"


def test_sqlite_master_refused():
    assert _code({"sql": "SELECT * FROM sqlite_master"}) == "not_authorized"


def test_both_fields_refused():
    model, err = validate_query({"sql": "SELECT 1 FROM holdings_v", "decline": "no"})
    assert model is None and err["code"] == "invalid" and "both" in err["detail"]


def test_neither_field_refused():
    model, err = validate_query({"sql": None, "decline": None})
    assert model is None and err["code"] == "invalid" and "neither" in err["detail"]


def test_write_hidden_in_cte_refused():
    assert _code({"sql": "WITH x AS (SELECT 1) DELETE FROM holdings"}) == "not_select"


def test_sqlquery_raises_validation_error():
    with pytest.raises(ValidationError):
        SQLQuery(sql="DROP TABLE holdings")


def test_other_models():
    cat = SchemaCatalog(tables=[{"table": "holdings_v",
                                 "columns": [{"column": "bdc", "description": "name"}]}])
    assert cat.names() == ["holdings_v"] and cat.text() == "holdings_v(bdc: name)"
    assert QueryRequest(question="  How many? ").question == "How many?"
    with pytest.raises(ValidationError):
        QueryRequest(question="   ")
    r = QueryResult(sql="SELECT 1", columns=["a"], rows=[[1]], row_count=1,
                    truncated=False, ms=0.1)
    assert r.row_count == 1


def test_constant_join_refused():
    q08_v2 = ("SELECT cur.name FROM filings cur JOIN (SELECT adsh, COUNT(*) AS n FROM holdings "
              "WHERE period_role = 'prior' GROUP BY adsh) p ON 1=1 WHERE cur.name = 'X' LIMIT 1")
    assert _code({"sql": q08_v2}) == "cross_join"
    assert _code({"sql": "SELECT 1 FROM filings a CROSS JOIN holdings b"}) == "cross_join"
    assert _code({"sql": "SELECT 1 FROM filings a JOIN holdings b ON (1 = 1)"}) == "cross_join"
    assert _code({"sql": "SELECT 1 FROM filings a JOIN holdings b ON TRUE"}) == "cross_join"


def test_keyed_joins_and_literals_pass():
    for ok in ["SELECT f.name FROM holdings h JOIN filings f ON f.adsh = h.adsh",
               "SELECT 'ON 1=1 CROSS JOIN' AS s FROM filings",          # inside a string literal
               "SELECT f.name FROM holdings h JOIN filings f ON f.adsh = h.adsh AND h.ddate > '2025-01-01'",
               "SELECT f.name FROM holdings h JOIN filings f ON h.adsh = f.adsh AND h.period_role = 'prior'"]:
        model, err = validate_query({"sql": ok})
        assert err is None, (ok, err)
