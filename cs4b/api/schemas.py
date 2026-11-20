"""Pydantic request and response models for every endpoint (they drive /docs)."""
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

Mode = Literal["replay", "live"]
MODE_HELP = ("replay: answers only from outputs/cache (free, no key). "
             "live: calls Gemini for requests not yet cached (needs GEMINI_API_KEY at startup).")


class ModeStatus(BaseModel):
    available: bool
    reason: Optional[str] = Field(None, description="Why the mode is unavailable, if it is.")


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    default_mode: Mode = "replay"
    modes: dict[Mode, ModeStatus] = Field(description=MODE_HELP)
    model: str
    mcp_server: str
    tools: list[str] = Field(description="The MCP server's tools, as listed over the protocol.")
    cached_responses: int
    recorded_questions: int

    model_config = ConfigDict(json_schema_extra={"example": {
        "status": "ok", "default_mode": "replay",
        "modes": {"replay": {"available": True, "reason": None},
                  "live": {"available": False, "reason": "Live mode isn't available: no GEMINI_API_KEY "
                                                          "was set when the API started. ..."}},
        "model": "gemini-3.5-flash-lite", "mcp_server": "askpanel-query",
        "tools": ["list_tables", "describe_table", "sample_values", "run_query"],
        "cached_responses": 30, "recorded_questions": 10}})


class RecordedQuestion(BaseModel):
    id: str
    category: str
    question: str
    follows: Optional[str] = Field(None, description="For a follow_up: the id of the question it follows.")

    model_config = ConfigDict(json_schema_extra={"example": {
        "id": "q03", "category": "follow_up", "follows": "q02",
        "question": "What is the combined fair value of those holdings?"}})


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    thread_id: Optional[str] = Field(
        None, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$",
        description="Continue this conversation (follow-ups). Omit to start a new one. A thread "
                    "keeps the mode it started in: a different mode starts a new thread.")
    mode: Mode = Field("replay", description=MODE_HELP)

    @field_validator("question")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("the question is blank")
        return v.strip()

    model_config = ConfigDict(json_schema_extra={"examples": [
        {"question": "Which ten BDCs have the largest total current fair value?", "mode": "replay"},
        {"question": "Which debt holdings at Golub Capital Private Credit Fund carry a PIK rate above 5%?",
         "mode": "replay"},
        {"question": "What is the combined fair value of those holdings?",
         "thread_id": "<thread_id returned by the Golub question above>", "mode": "replay"}]})


class TraceStep(BaseModel):
    """One node step. Extra keys from the agent (hashes, tokens, ...) are kept."""
    model_config = ConfigDict(extra="allow")
    step: int
    node: str
    ts: str
    outcome: Optional[str] = None
    attempt: Optional[int] = None


class AskResponse(BaseModel):
    thread_id: str
    mode: Mode
    thread_reset: bool = Field(False, description="True if the thread_id sent belonged to the other mode, "
                                                   "so this answer started a new thread.")
    previous_thread_id: Optional[str] = None
    turn: int = Field(description="1 for the first question on this thread, 2 for its first follow-up, ...")
    question: str
    answer: str
    declined: bool
    decline_reason: Optional[str] = None
    explanation: Optional[str] = Field(None, description="The model's own note on its SQL.")
    sql: Optional[str] = None
    columns: list[str] = []
    rows: list[list[Any]] = []
    row_count: int = 0
    truncated: bool = False
    usd: float = Field(description="Cost at the params.yaml list price (actual spend on the free tier is $0).")
    tokens: int
    model_calls: int
    fresh_model_calls: int = Field(0, description="Live mode: calls that really reached Gemini "
                                                  "(0 = replayed from the cache for free).")
    attempts: int = Field(description="Failed attempts that went down the repair edge (0 = first try worked).")
    stop: Optional[str] = Field(None, description="budget_usd or budget_tokens if the budget guard stopped it.")
    error: Optional[dict[str, Any]] = Field(None, description="The last refusal, if repair ran out.")
    trace: list[TraceStep]

    model_config = ConfigDict(json_schema_extra={"example": {
        "thread_id": "c-3f2a9b1e", "mode": "replay", "thread_reset": False, "previous_thread_id": None,
        "turn": 1, "question": "Which ten BDCs have the largest total current fair value?",
        "answer": "10 row(s)\nbdc | total_fair_value\nAPOLLO DEBT SOLUTIONS BDC | 25,367,235,000.00\n...",
        "declined": False, "decline_reason": None, "explanation": "Sums fair_value per BDC.",
        "sql": "SELECT bdc, SUM(fair_value) AS total_fair_value FROM holdings_v GROUP BY bdc "
               "ORDER BY total_fair_value DESC LIMIT 10",
        "columns": ["bdc", "total_fair_value"],
        "rows": [["APOLLO DEBT SOLUTIONS BDC", 25367235000.0]], "row_count": 10, "truncated": False,
        "usd": 0.0007939, "tokens": 2001, "model_calls": 1, "fresh_model_calls": 0, "attempts": 0, "stop": None, "error": None,
        "trace": [{"step": 1, "node": "load_schema", "ts": "2026-11-16T09:00:00-05:00"},
                  {"step": 2, "node": "generate", "ts": "2026-11-16T09:00:00-05:00", "attempt": 0},
                  {"step": 3, "node": "check", "ts": "2026-11-16T09:00:00-05:00", "outcome": "ok"},
                  {"step": 4, "node": "execute", "ts": "2026-11-16T09:00:00-05:00", "outcome": "ok"},
                  {"step": 5, "node": "summarize", "ts": "2026-11-16T09:00:00-05:00"}]}})


class ErrorBody(BaseModel):
    code: str
    message: str

    model_config = ConfigDict(json_schema_extra={"example": {
        "code": "cache_miss",
        "message": "This question isn't in the replay cache. Try one of the recorded questions, "
                   "or switch to live mode with a Gemini key."}})


class ErrorResponse(BaseModel):
    detail: ErrorBody


class ConversationCreate(BaseModel):
    mode: Mode = Field("replay", description=MODE_HELP)

    model_config = ConfigDict(json_schema_extra={"example": {"mode": "replay"}})


class Conversation(BaseModel):
    thread_id: str
    mode: Mode

    model_config = ConfigDict(json_schema_extra={"example": {"thread_id": "c-3f2a9b1e", "mode": "replay"}})


class Turn(BaseModel):
    turn: int
    question: str
    answer: Optional[str]
    sql: Optional[str]
    declined: bool
    usd: float
    model_calls: int


class ConversationHistory(BaseModel):
    thread_id: str
    mode: Mode
    turns: list[Turn]

    model_config = ConfigDict(json_schema_extra={"example": {"thread_id": "c-3f2a9b1e", "mode": "replay", "turns": [
        {"turn": 1, "question": "Which debt holdings at Golub Capital Private Credit Fund carry a PIK rate above 5%?",
         "answer": "15 row(s) ...", "sql": "SELECT identifier, ... FROM holdings_v WHERE ...",
         "declined": False, "usd": 0.000896, "model_calls": 1},
        {"turn": 2, "question": "What is the combined fair value of those holdings?",
         "answer": "1 row(s)\ncombined_fair_value\n106,150,000.00",
         "sql": "SELECT SUM(fair_value) AS combined_fair_value FROM holdings_v WHERE ...",
         "declined": False, "usd": 0.0008946, "model_calls": 1}]}})


class Column(BaseModel):
    column: str
    description: str = ""


class Table(BaseModel):
    table: str
    columns: list[Column]


class Schema(BaseModel):
    tables: list[Table]

    model_config = ConfigDict(json_schema_extra={"example": {"tables": [{"table": "holdings_v", "columns": [
        {"column": "bdc", "description": "the BDC's name"},
        {"column": "fair_value", "description": "fair value in US dollars"}]}]}})


class EconomicsLine(BaseModel):
    line: str
    value: str


class EconomicsTotals(BaseModel):
    questions: int
    usd_total: float
    usd_per_question: float
    model_calls_per_question: float
    repaired: int
    no_sql: int
    tokens_total: int
    analyst_minutes_per_question: float
    analyst_rate_usd: float
    hours_saved: list[dict[str, Any]]


class Economics(BaseModel):
    source: str
    lines: list[EconomicsLine] = Field(description="The five lines of outputs/economics.md.")
    computed: EconomicsTotals = Field(description="Recomputed from outputs/questions/ with askpanel.econ.")
