# Lab 25: OpenAI record/replay agent

## Current completion status

The provider adapter, model routing, replay runner and offline tests are implemented.
A genuine OpenAI dev-01 recording completed on 2026-11-11. Both offline replays
matched the recording byte for byte with zero provider calls. Evidence is stored in
`evals/recordings/dev-01/verification.json`. Synthetic unit tests remain separate
from the real-recording acceptance test.

## Record once, then replay twice

From `cs3b/`:

```bash
source .venv311/bin/activate
python -m services.agent.run record
```

Optionally copy `cs3b/.env.example` to `cs3b/.env` and fill in `OPENAI_API_KEY`.
The record command loads that exact file automatically; existing environment variables
take precedence. `.env` is ignored by Git. Verify mode does not load it.

If no key is configured, enter the OpenAI API key at the hidden prompt, then the fictional Priya session token
`priya-fixture-token`. Keys entered at the prompt stay in process memory and are not saved by the runner.
Keys you put in `.env` remain in that local file. Alternatively
set OPENAI_API_KEY and CREDITWATCH_SESSION_TOKEN in the launching environment.
Record mode makes paid OpenAI API calls for cache misses; rerunning it reuses cached
responses. It runs fixture development task dev-01, saves the completed run, and
immediately verifies two offline replays. Model access/billing must be enabled in
the OpenAI account. No extra OpenAI SDK dependency is required (HTTPS REST adapter).

Later, with no key and no network:

```bash
python -m services.agent.run verify
```

Files under `evals/recordings/dev-01/`:

- `manifest.json`: frozen context, tool schemas, task, clock, routes, prices and budgets.
- `responses/`: actual model responses, keyed by complete request hashes.
- `tool_observations.json`: frozen read-tool results keyed by tool and arguments.
- `recorded.json`: completed real-model run with assessments, note and traces.
- `replay-1.json`, `replay-2.json`: byte-identical offline reruns.
- `verification.json`: SHA-256 and equality results.

Commit the fixture-only recording bundle after review so CI can replay it. Do not
commit real client records or credentials. If changing context, models or prompts,
choose a fresh bundle with `--bundle evals/recordings/dev-01-v2`; do not overwrite
an earlier recording's provenance. The bundle freezes inputs deliberately.

## How it works

`model.py` uses the OpenAI Responses API with a validated next-decision schema.
The model selects a permitted tool and JSON arguments or emits a final note. This
is application-level dispatch, not native Responses function-call items. Tool inputs
are validated again by the Lab 24 runtime. `ReplayClient` surrounds the provider;
replay never calls OpenAI and a cache miss raises an error.

`run.py` runs triage and materiality using the small model and passes their results
into the main agent loop. The model routes and per-million-token prices are in
`models.yaml`. Defaults are pinned GPT-5.4 Mini and GPT-5.4 snapshots. Change both
model name and prices together if using other models. Estimated costs conservatively
charge cached input at full input rates. Recorded costs remain in replay traces to
preserve equality; actual replay API charges are zero.

The demo is limited to READ tools for dev-01. It uses the same Lab 24 runtime as
MCP, directly in-process (not a new MCP transport). It does not connect the browser
chat, send email, or execute write tools. Mutable side effects would need separate
snapshot/replay treatment before expanding this runner to other tasks.

The lab clock is frozen when recording. The original loop's budgets are post-call
guards: a model call can push recorded cost over the cap before the loop stops.
Triage/materiality costs count against the same overall task budget. Incomplete
runs, missing required dev-01 tool calls, or replay mismatch do not produce a passing
verification report. Client note quality still needs review; equal traces prove
repeatability, not factual accuracy.

## Test

```bash
python -m pytest tests/test_agent_replay.py -q -rs
python -m pytest -q
```

Synthetic tests create temporary recordings and prove routing, fail-closed misses,
zero-network replay, provider response parsing and budget enforcement. The separate
real-recording test uses the saved live bundle when present. CI has no API key and
runs replay-only tests.

Official references:
- https://developers.openai.com/api/docs/guides/structured-outputs
- https://developers.openai.com/api/docs/models/gpt-5.4-mini
- https://developers.openai.com/api/docs/models/gpt-5.4


## Lab 30: authenticated corrections and before/after evaluation

```bash
python -m services.learning.run record
python -m services.learning.run verify
python -m services.learning.run report
python -m pytest tests/test_learning.py -q
```

`record` uses the existing OpenAI provider, RoutedModel and read-only agent loop.
It loads the local `.env` without logging credentials. The fixture-only evaluation
freezes the original workspace context, model configuration, prompt and tool
observations. Five stages (baseline plus four corrections), each with A and B tasks,
produce ten notes. Each correction's paired comparison uses the identical task and
evidence on either side; consecutive after/before states reuse the same cached
answer. Frozen factual briefings are supplied directly for this experiment; it does
not add new small-model triage calls. Per-task step, token and dollar limits remain
those in `params.yaml`. Agent responses may already satisfy a rule before correction.

The correction path derives authority from the message's session token and checks
mandate authorization. Unauthenticated text remains a proposal. It rejects changed
content under an existing message ID and is idempotent for an identical message.
Preparatory rule application uses a scratch workspace. Only after the real recording
and double replay complete are the four authenticated messages applied to working
`agent/PRINCIPAL.md`, with `memory_write` events in
`logs/audit/learning-corrections.jsonl`. These four corrections are general operating
rules; client-specific confidential facts should not be put into global PRINCIPAL.md.
The injected lab clock is frozen for comparability, not a real elapsed-time record.

`verify` is offline, makes no provider calls, and checks that answers, contexts,
traces and usage match the saved recording twice. `report` recomputes current grades
from the same recordings and republishes result artifacts offline. It also checks
that already-written rules have provenance; it will not legitimize pre-written rules.
A fresh baseline must start from the seed principal file; existing learning is never
silently reset. Keep the existing manifest/cache to replay this completed experiment.

Artifacts:
- `evals/recordings/learning/`: frozen inputs, provider responses, original run outputs,
  and replay verification. No API/session token is saved in this recording.
- `outputs/learning/msg-101.jsonl` through `msg-104.jsonl`: A/B before-and-after text,
  traces, adherence checks and earlier-rule regressions.
- `reports/learning/adherence.json`: current scores, cost estimate and task-completion flags.
- `reports/learning/review_notes.json`: rubric changes and assistant review observations.

The current grader is a transparent, non-vacuous fixture heuristic, not a semantic
oracle. It requires coverage of expected signals, explicit qualification of background
PIK, point changes for markdowns, exposure in the opening sentence and accession
citations on matching observations. Explicit planning-only outputs fail the task.
Shortened borrower names and hyphenated points are accepted. The original raw answers
and original grades remain under `runs/`; updated grades live in published reports.
Do not edit model outputs to improve scores, or confuse passing software tests with
perfect agent adherence. The recorded experiment includes actual regressions and
incomplete answers. The price estimate uses the recorded model configuration and is
not a billing statement. Follow [OpenAI's evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
when expanding the dataset and reviewing automated grading against human judgments.
