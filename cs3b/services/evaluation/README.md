# Lab 31: evaluation and unit economics

Run from `cs3b/` with `.venv311` active:

```bash
python -m pip install -e . --no-deps
lantern eval run --suite dev --mode replay
lantern scenario --mode replay
lantern economics
python -m pytest -q
PYTHONPATH=src python -m creditwatch.check
```

Replay uses recorded OpenAI responses and actual server observations. It makes no provider calls and does not instantiate the tool runtime, send another message, or write another watchlist entry. It regenerates evaluation reports and verifies two replays against the original result. Missing responses or changed requests fail closed. CI runs offline.

Record mode uses the key and session token from the ignored `.env` file. It costs money when a response is not already cached:

```bash
lantern eval run --suite dev --mode record
lantern scenario --mode record
```

Existing bundles resume from cached responses and journals. To deliberately start a new experiment, use a new bundle version in the runner; do not delete evidence or overwrite an earlier experiment's context. Current dev bundles are `evals/recordings/suite-dev-v2/`; the completed scenario is `evals/recordings/release-morning-v3/`. Earlier attempts remain available. Record timing from resumed work is not fresh end-to-end latency.

## What each file does

- `runner.py`: authenticates the session, freezes mandate-scoped context, routes triage to the small model, runs category-based workflows, executes real server calls, checks final-response isolation, and saves/replays observations. Workflow routing never reads the grader's `expect` list. The model supplies tool arguments and note content. Its previous arguments stay in history so approved payloads can be reproduced exactly.
- `grading.py`: checks required result fields, expected action order, forbidden executed actions, tool classes, client isolation, approval evidence, heartbeat execution and required correction context.
- `cli.py`: provides `lantern eval run`, writes one result per JSONL line and a readable checks report; a failing suite exits 1.
- `scenario.py`: runs release detection at the fixture's 06:00 clock, morning brief delivery at 07:30, then the real model/server draft → approval → mock send → separate approval → watchlist write workflow. Durable server receipts demonstrate both writes.
- `economics.py`: combines recorded token-cost estimates (including failed development attempts) with explicit monthly assumptions in `params.yaml`. Reports cost per passed task, scenario cost, cost per mandate-month, analyst-time sensitivity and illustrative failure loss.

## Important interpretation

The eight dev tasks are fictional. Human approval in these tests is an explicitly labelled fixture controller, not the model granting itself permission or a real approval from Priya. Email goes only to the local mock outbox. Approval handles in recordings are opaque references; actual HMAC tokens stay in ignored scratch state.

For the recipient-change test, a fixture controller creates an approved draft, changes its recipients, and proves the real server blocks sending it. The action actor fields identify fixture actions separately from agent actions. A pending watchlist approval is reported as a requested action, never an executed write.

The first run exposed skipped steps and a refusal repeating another client's name. The revised runner guides each workflow step and blocks cross-client final text. The reply task also exposed a wrong-recipient draft; the model corrected it to the active client contact, with the rejected attempt retained. Passing automated checks is not a claim that every sentence of every note has been independently reviewed.

The starter supplies Appendix G output fields and checks. A separate full Appendix G document and variant task file are not present. `lantern eval run --suite variant --mode replay` reports this as unavailable, not passed. Place official variants in `evals/tasks/variant.jsonl`; record before replay. Optional fixture controls belong in `evals/tasks/variant_controls.json` and must reflect the supplied task setup, not manufacture successful answers.

Monthly hosting, activity, review time and incident-risk inputs are assumptions. Token prices are configured estimates rather than the invoice; cached-input discounts are not applied. The scenario's A cost is a proxy for either mandate. Potential analyst-time value is not verified savings. The 90-minute simulated hold is distinct from measured process time; publication-to-delivery latency cannot be inferred from this fixture.

## Review artifacts

- `outputs/tasks/dev.jsonl`: final task results and action traces.
- `reports/evals/dev.json`: current pass/fail checks.
- `reports/evals/dev-attempt-1.json`: initial failures.
- `evals/recordings/...`: frozen context, model response caches, server journals and double-replay verification.
- `outputs/scenario/release_morning.json`: completion IDs and timing.
- `evals/recordings/release-morning-v3/server_artifacts.json`: actual mock outbox and watchlist receipts.
- `reports/economics/unit_economics.json` and `mandate_month.csv`: cost calculations and assumptions.
- `logs/audit/eval-*.jsonl`: durable server audit events.
