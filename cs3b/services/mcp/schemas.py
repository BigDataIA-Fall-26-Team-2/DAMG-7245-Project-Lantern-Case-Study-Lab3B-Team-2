"""Validated contracts for the closed tool catalog."""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

class EmptyInput(ToolInput):
    pass

class ScopeInput(ToolInput):
    scope: str = Field(min_length=1)

class HoldingsInput(ScopeInput):
    bdc: str | None = None

class FilingInput(ToolInput):
    adsh: str = Field(pattern=r"^\d{10}-\d{2}-\d{6}$")

class MemoryInput(ScopeInput):
    query: str = ""
    limit: int = Field(default=5, ge=1, le=50)

class ProposalInput(ScopeInput):
    content: str = Field(min_length=1, max_length=10000)

class WatchlistEntry(ToolInput):
    bdc: str = Field(min_length=1)
    note: str = Field(min_length=1, max_length=10000)
    citations: list[str] = Field(min_length=1)

class WatchlistInput(ScopeInput):
    entry: WatchlistEntry
    approval_token: str = ""

class DraftInput(ScopeInput):
    to: list[str] = Field(min_length=1)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=20000)
    attachments: list[str] = Field(default_factory=list)

class ApprovalInput(ToolInput):
    action: Literal["send_email", "watchlist_write"]
    payload: dict[str, Any]

class SendInput(ScopeInput):
    draft_id: str = Field(pattern=r"^draft-[a-f0-9]{32}$")
    approval_token: str = ""

class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

class MandateProfileOutput(Output):
    client: str
    positions: dict[str, float]

class MandateSummary(Output):
    mandate: str
    client: str

class MandatesOutput(Output):
    mandates: list[MandateSummary]

class Holding(Output):
    adsh: str
    name: str
    identifier: str
    fair_value: float | None
    principal: float | None
    pik_rate: float | None
    source_rows: str

class HoldingsOutput(Output):
    holdings: list[Holding]

class Signal(Output):
    adsh: str
    name: str
    rule: str
    identifier: str
    row: str
    prior_row: str
    before: float | str
    after: float | str

class SignalsOutput(Output):
    signals: list[Signal]

class FilingOutput(Output):
    adsh: str
    source: str
    rows: list[dict[str, Any]]
    metadata: dict[str, Any]

class WatchlistOutput(Output):
    text: str
    entries: list[dict[str, Any]]

class MemoryHit(Output):
    text: str
    source: str

class MemoryOutput(Output):
    matches: list[MemoryHit]

class ProposalOutput(Output):
    proposal_id: str
    status: Literal["proposed"]

class WatchlistWriteOutput(Output):
    watchlist_entry_id: str
    status: Literal["written", "already_written"]

class DraftOutput(Output):
    draft_id: str
    scope: str
    to: list[str]
    subject: str
    body: str
    attachments: list[str]

class ApprovalOutput(Output):
    request_id: str
    payload_hash: str
    status: Literal["pending"]

class SendOutput(Output):
    outbox_message_id: str
    status: Literal["sent", "already_sent"]

class ErrorDetail(Output):
    code: str
    message: str

INPUTS = {
    "list_mandates": EmptyInput, "bdc_holdings": HoldingsInput,
    "bdc_signals": ScopeInput, "get_filing": FilingInput,
    "mandate_profile": ScopeInput, "watchlist_read": ScopeInput,
    "memory_read": MemoryInput, "memory_propose_write": ProposalInput,
    "watchlist_write": WatchlistInput, "draft_email": DraftInput,
    "request_approval": ApprovalInput, "send_email": SendInput,
}
OUTPUTS = {
    "list_mandates": MandatesOutput, "bdc_holdings": HoldingsOutput,
    "bdc_signals": SignalsOutput, "get_filing": FilingOutput,
    "mandate_profile": MandateProfileOutput, "watchlist_read": WatchlistOutput,
    "memory_read": MemoryOutput, "memory_propose_write": ProposalOutput,
    "watchlist_write": WatchlistWriteOutput, "draft_email": DraftOutput,
    "request_approval": ApprovalOutput, "send_email": SendOutput,
}
