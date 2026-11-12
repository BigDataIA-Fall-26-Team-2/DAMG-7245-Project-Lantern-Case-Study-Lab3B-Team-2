# Lab 24: closed MCP tool server

Run from `cs3b/` using `.venv311`. The registry matches `creditwatch.catalog.CATALOG`,
and the running server exposes exactly those 12 names. All tools validate requests
with Pydantic and validate successful data against a tool-specific output model.
Responses use `{ "ok": true, "data": ... }` or
`{ "ok": false, "error": { "code": ..., "message": ... } }`.
Application denials use this envelope, not MCP's protocol-level `is_error` flag.
Malformed MCP requests can also be rejected by the SDK before a handler executes.

## Files

- `schemas.py`: input/output models and per-tool model maps.
- `runtime.py`: session scope, public reads, client files, policy checks, proposals,
  persistent drafts, approval requests, exact-payload grants, and mock sends.
- `server.py`: the 12 MCP wrappers, authenticated startup, and registry.
- `errors.py`: stable typed application errors.
- `approve.py`: human-only approval console. This is NOT an MCP tool.
- `handlers.py`: the original standalone mandate-profile teaching example, retained
  so the original eight tests continue to work. The full server uses `runtime.py`.

## Start

```bash
source .venv311/bin/activate
python -m services.mcp.server --mandate mandate_a
```

Enter the fixture session token `priya-fixture-token` when prompted. After login,
this is an MCP stdio process, not an interactive chat: it waits for an MCP client.
Stop it with Ctrl+C. The authenticated identity and mandate are fixed at startup.
For an MCP host launching a subprocess, pass `CREDITWATCH_SESSION_TOKEN` through
its environment instead of prompting; never put real tokens in committed config.
The launch command is the environment's Python with arguments
`-m services.mcp.server --mandate mandate_a` and working directory `cs3b`.
Use this explicit startup entry point rather than `mcp dev server.py`, since the
server requires authenticated session setup, not an unauthenticated global instance.

## Inputs and returned data

| Tool | Arguments | Data |
| --- | --- | --- |
| list_mandates | none | active mandate ID and client name only |
| bdc_holdings | scope, optional bdc | current holdings |
| bdc_signals | scope | signals with current/prior row evidence |
| get_filing | adsh | local filing rows and recorded EDGAR metadata |
| mandate_profile | scope | client and positions |
| watchlist_read | scope | watchlist text and managed entries |
| memory_read | scope, optional query and limit | matching memory/log lines with sources |
| memory_propose_write | scope, content | pending proposal ID |
| watchlist_write | scope, entry, approval_token | watchlist entry ID |
| draft_email | scope, to, subject, body, optional attachments | stored draft |
| request_approval | action, payload | pending request ID and payload hash |
| send_email | scope, draft_id, approval_token | mock outbox message ID |

Public data tools accept `public` or the active mandate scope, consistent with the
starter `require_scope`. Client tools accept only the active mandate. Tool callers
cannot supply a principal, authenticated origin, filesystem path, or alternate session.
`get_filing` is deliberately offline: it does not fetch full SEC HTML or pretend
that panel rows are the complete filing. `bdc_signals` uses the starter baseline
pairing; custom pairing belongs to the later signals lab. Memory search reads the
active mandate's MEMORY.md and logs; it does not write a search index.
Attachments are literal text labels in the draft, not file paths to read or upload.

## Approval workflow

1. Call `draft_email`; retain `data.draft_id`.
2. Call `request_approval` with action `send_email` and payload
   `{ "draft_id": "draft-..." }`. This does NOT grant approval.
3. Priya runs:

```bash
python -m services.mcp.approve req-... --mandate mandate_a
```

Authenticate, read the exact payload, and paste the displayed payload hash to
confirm. The console prints the approval token. This separate console is the
human control plane and must not be exposed to the model as a tool.
4. Pass that token and draft ID to `send_email`. It writes only
   `outputs/outbox/`, never real email. Repeated approved sends are idempotent.

For watchlists, request action `watchlist_write` with payload
`{ "scope": "mandate_a", "entry": { "bdc": "exact held BDC", "note": "...", "citations": ["..."] } }`.
After human approval, call `watchlist_write` with the identical entry and token.
Citation strings are required but semantic evidence verification belongs to later evaluation.

Tokens bind principal, mandate, action and exact payload and respect the configured
TTL and lab clock. Changing any approved content requires a new approval. A signed
token also needs a recorded human grant. Tool-origin memory always stays a proposal;
this tool cannot edit PRINCIPAL.md. State lives under each mandate's `tool_state/`
and proposals folder. Watchlist writes preserve the existing text before the managed
section. Audit logs include IDs and decisions, not tokens or message bodies.

## Checks

```bash
python -m pytest tests/test_mcp_tools.py tests/test_mcp_mandate_profile.py -q
PYTHONPATH=src python -c "from services.mcp.server import REGISTRY; from creditwatch.catalog import conformance; print(conformance(REGISTRY))"
python -m pytest -q
```

Tests use temporary workspaces and a temporary mock outbox. They cover all 12 tools
through MCP, the actual wire catalog, invalid inputs, cross-client scope, human
approval, tampering, expiry, duplicate sends, restricted recipients, proposal origin,
and stdio startup. This completes the local Part 1 implementation against the shipped
catalog; remaining case-study self-check failures belong to later work.


## Lab 27: memory and reviewed compaction

Memory reads search the active mandate's `MEMORY.md` and original daily logs.
These durable Markdown files are the working server's store; the notebook's
SQLite demonstration is not required by the server. New chat sessions include
active-mandate memory within the configured context budget. Use `memory_read`
for targeted recall when all notes do not fit. Pending proposals are excluded.

Run from `cs3b/` with the environment activated. Preview an exclusive date cutoff:

```bash
python -m services.mcp.compact --mandate mandate_a --before 2026-10-15
```

Enter Priya's session token at the hidden prompt. Review the printed diff, then
apply that exact version using its printed hash:

```bash
python -m services.mcp.compact --mandate mandate_a --before 2026-10-15 --apply REVIEW_HASH
```

Replace `REVIEW_HASH` with the preview's value. Changed source logs or memory
invalidate it. Compaction retains full source text and links, existing curated
memory, and original logs; it consolidates notes rather than using an AI summary.
Applied compactions record metadata in the mandate's `audit/memory.jsonl`.
The command is a human control, not a thirteenth MCP tool. It assumes the local
single-writer lab workflow; concurrent compaction/writes need transactional locking.

```bash
python -m pytest tests/test_governed_memory.py -q
```

These deterministic tests verify cross-session recall and isolation, including
real MCP client calls, without making model API calls. They do not claim to run
unreleased external grading tasks or an end-to-end conversational model.


## Lab 29: action policy and audit review

`params.yaml` now declares `action_policy.tool_classes`, `class_policies`, and
tool-specific overrides. Startup checks these against the closed catalog and
rejects configurations that remove required approval or permit destructive actions.
A tool may be disabled with `forbidden`. Draft/read actions run automatically;
internal writes produce an audit notification; send and watchlist changes require
exact-payload approval; the control path is bound to the configured principal.
Content, recipient and mandate checks remain server-enforced at action time.

An approval request is pending, not permission to send. The human console checks
identity, displays the exact envelope, and requires its fingerprint as confirmation:

```bash
python -m services.mcp.approve REQUEST_ID --mandate mandate_a
```

If the stored draft changed after the request, request approval again. The server
rechecks content policy at grant and send time. Changes to recipients, subject,
body or attachments invalidate the old approval. A token is invalid at its expiry
instant, for the wrong person/action/payload, or without the recorded human grant.
Successful repeats return `already_sent` or `already_written` in the local lab.
The starter signing-key fallback is for fixture/replay exercises only; the key is
never exposed as an MCP tool or written to the audit log.

Authenticated MCP sessions save logs under `logs/audit/mcp-*.jsonl`. Blocked calls
now include a `policy_block` event with tool, scope, decision, rule ID, reason and
argument fingerprint. Approval checks also record attempted/approved payload
fingerprints. Reasons include `payload_changed`, `expired`, `missing_token`,
`wrong_approver`, and `missing_human_grant`. No bodies, recipient lists or tokens
are copied into these audit events. Each server session has its own log file;
event IDs are unique within that file. Notifications here are saved audit events,
not external messages.

```bash
python -m pytest tests/test_action_controls.py -q
python -m services.mcp.demo_actions
```

The second command is explicitly a fictional **test with simulated human grants**.
It edits an approved recipient list, proves the send is blocked, obtains a new
test grant and proves local outbox delivery. It also verifies a retry and an
approved watchlist write in an isolated `.cache` workspace. It does not obtain
real human consent or send external email. The report under `reports/actions/`
links its persistent audit log and mock-outbox file. Outbox files and scratch state
are ignored by Git; rerun the exercise to recreate them on another checkout.

Notebook 29 preserves its original examples and now includes saved-log review and
an executed implementation-verification section. Notebook-only example logs use
`lab29-demo-*`; server-backed exercises use `lab29-actions-*`, so simulated evidence
is distinguishable from interactive MCP sessions. All available notebook blocked
cases and additional token/configuration cases are tested; a separate Part 6
specification was not present in this checkout.
