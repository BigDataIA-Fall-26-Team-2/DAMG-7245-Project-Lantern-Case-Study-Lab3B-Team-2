"""The contract between the model, the agent and the server (Lab 33B).

The model's reply is an object with rules, not a string. SQLQuery runs the kit's
static gate (no database needed); the server's gate.run_query stays the authority.
validate_query() turns a refusal into {"code", "detail"} with the gate's own code,
so the repair edge can tell the model exactly what went wrong.

One rule of our own sits on top of the gate: a join on a constant (ON 1=1, ON 1,
ON TRUE) or a CROSS JOIN is refused with code cross_join. Such SQL is valid and
read-only, so the gate passes it, but over this panel it silently pairs every
filing with every other (failure 5 in outputs/failures.md); refusing it sends the
model down the repair edge instead of returning wrong numbers.
"""
import re
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from pydantic_core import PydanticCustomError

from agent import ROOT  # noqa: F401  (puts src/ on sys.path)
from askpanel import gate


_STRINGS = re.compile(r"'(?:[^']|'')*'")
_COMMENTS = re.compile(r"(--[^\n]*\n?)|(/\*.*?\*/)", re.S)
_CROSS = re.compile(r"\bCROSS\s+JOIN\b|\bON\s*\(*\s*(?:1\s*=\s*1|1|TRUE)\s*\)*(?=\s|\)|$)", re.I)


def cross_join(sql: str) -> Optional[str]:
    """The offending text if sql joins on a constant or uses CROSS JOIN, else None."""
    m = _CROSS.search(_COMMENTS.sub(" ", _STRINGS.sub("''", sql)))
    return m.group(0).strip() if m else None


class ColumnInfo(BaseModel):
    column: str
    description: str = ""


class TableInfo(BaseModel):
    table: str
    columns: list[ColumnInfo]


class SchemaCatalog(BaseModel):
    """What the model reads: every table it may query, each column with a description."""
    tables: list[TableInfo]

    def names(self) -> list[str]:
        return [t.table for t in self.tables]

    def text(self) -> str:
        """The same layout as askpanel.nodes' load_schema node."""
        return "\n".join(
            f"{t.table}(" + ", ".join(
                f"{c.column}: {c.description}" if c.description else c.column
                for c in t.columns) + ")"
            for t in self.tables)


class QueryRequest(BaseModel):
    """One analyst question, with the conversation so far (for follow-ups)."""
    question: str = Field(min_length=1)
    history: list[dict[str, Any]] = Field(default_factory=list)
    thread_id: Optional[str] = None

    @field_validator("question")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise PydanticCustomError("empty", "the question is blank")
        return v.strip()


class SQLQuery(BaseModel):
    """The model's reply: exactly one of sql (a single gated SELECT) or decline."""
    sql: Optional[str] = None
    decline: Optional[str] = None
    explanation: str = ""

    @field_validator("sql")
    @classmethod
    def gated(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        try:
            v = gate.static_check(v)
        except gate.GateError as e:
            raise PydanticCustomError(e.code, "{detail}", {"detail": e.detail}) from None
        bad = cross_join(v)
        if bad:
            raise PydanticCustomError("cross_join", "{detail}", {"detail": (
                f"'{bad}' joins without a key; link every join on adsh "
                "(or use conditional aggregation in one pass)")})
        return v

    @field_validator("decline")
    @classmethod
    def decline_text(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None or not v.strip() else v.strip()

    @model_validator(mode="after")
    def exactly_one(self):
        if self.sql is not None and self.decline is not None:
            raise PydanticCustomError("invalid", "give exactly one of sql or decline, not both")
        if self.sql is None and self.decline is None:
            raise PydanticCustomError("invalid", "give exactly one of sql or decline; got neither")
        return self


class QueryResult(BaseModel):
    """What the server's run_query returns (gate.run_query's dict, typed)."""
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    ms: float


def validate_query(data: dict) -> tuple[Optional[SQLQuery], Optional[dict]]:
    """(SQLQuery, None) if the reply is acceptable, else (None, {"code", "detail"})
    with the gate's code (empty, not_select, multiple_statements, not_authorized,
    invalid) or our cross_join."""
    fields = {k: data.get(k) for k in ("sql", "decline", "explanation")}
    if fields["explanation"] is None:
        fields["explanation"] = ""
    try:
        return SQLQuery(**fields), None
    except ValidationError as e:
        err = e.errors()[0]
        detail = err.get("ctx", {}).get("detail") or err["msg"]
        return None, {"code": err["type"], "detail": detail}
