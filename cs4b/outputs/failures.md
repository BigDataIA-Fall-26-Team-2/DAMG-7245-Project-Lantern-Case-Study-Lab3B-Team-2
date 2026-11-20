# Failure log

Five real failures from our own recordings on the real panel (73 BDC 10-Qs, 2026-06-30), model
`gemini-3.5-flash-lite`. Each was found by checking the recorded answer against an independent
query of our own on `data/panel.sqlite`, and each was fixed in the system (view, column
descriptions, prompt rules, a validator), never by rewording a question: the text of all ten
questions in `questions/questions.yaml` is the same in every run.

Evidence. Three recordings, all kept:
- v1: `outputs/runs/v1/<id>.json` (kit column descriptions, our first prompt rules)
- v2: `outputs/runs/v2/<id>.json` (after fixes 1 to 3)
- v3: `outputs/questions/<id>.json` (after fixes 4 and 5; the replayable final run)

Every model response, with its raw text, is in `outputs/cache/<request_key>.json`; the
request key is in each `generate` step of the trace. v1 and v2 do not replay under the
current code (the schema text, and so every request key, changed), so they are an archive.

## Failure 1
Question: q04 (aggregation) "For Antares Strategic Credit Fund, how many current holdings and how much fair value fall under each investment type?"
What went wrong: v1 trace (request `97789522106b`, check ok, execute ok, 1 model call) ran `... WHERE UPPER(bdc) LIKE '%ANTARES STRATEGIC CREDIT FUND%' GROUP BY investment_type`, which also matches ANTARES STRATEGIC CREDIT FUND II LLC. It answered DEBT 1,622 / EQUITY 99 / UNKNOWN 82 holdings; the fund's own figures are 1,326 / 92 / 70 (the other 296 / 7 / 12 belong to Fund II). No error, so no repair: a silently wrong answer. The cause was our own prompt rule, which suggested LIKE for BDC names.
What fixed it: `agent/graph.py` `schema_with_values`: load_schema now fetches the exact BDC names (and investment types) through the MCP `sample_values` tool and adds them to the schema, and the prompt rule in `agent/model.py` says to filter with `bdc = '<exact name>'` and never LIKE. v2 and v3 (request `1f28a563642c`) use `WHERE bdc = 'ANTARES STRATEGIC CREDIT FUND'` and return 1,326 / 92 / 70.

## Failure 2
Question: q05 (aggregation) "Across the whole panel, what share of current fair value is debt and what share is not?"
What went wrong: v1 trace (request `021cb05d4c0d`, 1 model call) split on `is_debt` and answered 92.30% debt / 7.70% not. The kit's description told the model `is_debt` is "1 for debt (has principal), 0 for equity", but on our panel is_debt only means a principal is reported: 3,987 DEBT-typed holdings ($8.83B) have no principal (is_debt 0) and 115 EQUITY holdings ($0.27B) have one (is_debt 1). The kit's `investment_type` description ("e.g. First Lien Senior Secured Debt [Member]") also did not match our values (DEBT, EQUITY, UNKNOWN, OTHER).
What fixed it: panel-specific column descriptions in `services/mcp/server.py` (`DESCRIPTIONS`: is_debt is "NOT a debt/equity label", investment_type lists our four values), the exact investment_type values in the schema (fix of Failure 1), and a prompt rule to split by investment_type with UNKNOWN reported separately. v2 and v3 (request `1daf1bfdd267`) answer DEBT 76.68%, UNKNOWN 21.80%, EQUITY 1.52%, OTHER 0.006%, which matches our check.

## Failure 3
Question: q08 (over_time) "How did Apollo Debt Solutions BDC's total fair value and number of holdings change from the prior schedule to the current one?"
What went wrong: v1 trace (request `7aa665b42aa6`, 1 model call) returned two rows, prior (815 holdings, $24,515,628,000) and current (834, $25,367,235,000), and never computed the change the question asks for; the answer the analyst sees is "2 row(s)" of levels.
What fixed it: a prompt rule in `agent/model.py`: for a change between schedules, return prior, current and change (current - prior) as columns. This rule alone produced Failure 5 in v2; with the Failure 5 fixes, v3 (request `4ebc41471e71`) returns one row: 815 to 834 holdings (+19) and $24,515,628,000 to $25,367,235,000 (+$851,607,000).

## Failure 4
Question: q02 (lookup) "Which debt holdings at Golub Capital Private Credit Fund carry a PIK rate above 5%?" and its follow-up q03 "What is the combined fair value of those holdings?"
What went wrong: a failure caused by our own fix of Failure 2. v2 trace (request `6f3327c2e565`) filtered `investment_type = 'DEBT' AND pik_rate > 0.05` (the PIK condition was the same as v1, and v1's LIKE and v2's exact `bdc =` match the same single fund; only the debt filter changed, from v1's `is_debt = 1`) and returned 7 rows instead of 15: it dropped 8 "One stop" loans that the filing did not tag (investment_type UNKNOWN) but that report a principal (Any Hour, Inhance, Panzura, Pluralsight, two RW AM Holdco, Striim, Transform Bidco). The follow-up q03 (request `233e1fa26685`) inherited the filter from the thread history and answered $88,966,000 instead of $106,150,000.
What fixed it: one definition of a debt holding in the prompt rules: `investment_type = 'DEBT' OR (investment_type = 'UNKNOWN' AND is_debt = 1)`, EQUITY never debt (the Modernizing Medicine preferred stock with a 13% PIK dividend stays out). v3 q02 (request `581eecd624f1`) returns 15 rows and q03 (request `6ff750f60f1d`) $106,150,000; q07 now uses the same definition (Fidus 33 of 115 debt holdings with PIK).

## Failure 5
Question: q08 (over_time), the same question as Failure 3.
What went wrong: a failure caused by our own fix of Failure 3, and the worst kind: valid, read-only SQL with wrong numbers. v2 trace (request `e7d7571a7d6a`, check ok, execute ok, 1 model call) joined the prior-schedule subquery `ON 1=1` (no adsh link) and took `LIMIT 1`, so its "prior" figures, 395 holdings and $1,013,671,210, are STELLUS CAPITAL INVESTMENT CORP's prior schedule; it reported Apollo's change as +439 holdings and +$24,353,563,790 (true: +19 and +$851,607,000). The gate passes this query: it is one SELECT over allowed tables.
What fixed it: two changes. (1) A validator in our contract, `agent/contract.py` `cross_join`: a join on a constant (ON 1=1, ON 1, ON TRUE) or a CROSS JOIN is refused with code `cross_join`, so the check node sends it down the repair edge instead of to the server; run over all 20 v1 and v2 queries it refuses exactly this one (`tests/test_contract.py::test_constant_join_refused`). (2) A prompt rule giving the one-pass pattern for changes (`holdings h JOIN filings f ON f.adsh = h.adsh` with conditional sums). v3 (request `4ebc41471e71`) uses that pattern and returns Apollo's own figures (815 to 834, $24.52B to $25.37B). In v3 the model wrote a keyed query first time, so the validator was not exercised in a recorded trace; it is covered by the unit test.

### Not failures (our check queries were wrong)
- v1 q02 returned 15 rows where our first check query found 16: the extra row is Modernizing Medicine, Inc. | Preferred stock (EQUITY, no principal, 13% PIK dividend), not a debt holding. v1 q03 ($106,150,000) was right for the same reason.
- v1 q07 Fidus 31 of 102 versus our check's 33 of 102: our check counted PIK on non-debt rows in the numerator.

### Data note (Lab 32B, not an agent failure)
46 current rows of our Lab 3B panel have a principal but no fair value (mostly unfunded revolvers and delayed-draw loans, a few equity units with the unit count in principal), so `price` cannot be computed and the kit's view check (`askpanel.db.check_view`, which requires a price on every row with principal > 0) failed on the real panel. `tools/prepare_real_panel.py` copies the panel and clears principal on exactly those 46 rows (it prints the count); nothing is invented, and fair value totals per filing are unchanged.
