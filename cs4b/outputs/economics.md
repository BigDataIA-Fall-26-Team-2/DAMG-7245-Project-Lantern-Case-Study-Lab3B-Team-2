# Unit economics

From our final recording (v3, `outputs/questions/`, model `gemini-3.5-flash-lite`) on the real
panel, with v1 and v2 (`outputs/runs/`) for quality and failure rates. Token counts, dollar cost
and latency per call are read from the traces and from `outputs/cache/<request_key>.json`.
A task is one of our ten questions; it is completed when the answer (or the decline) matches
our independent check query.

| Line | Ask the Panel |
|---|---|
| Cost per completed task | $0.000907 per question at the paid list price ($0.009072 for 10 of 10 completed; 19,315 input + 1,311 output tokens; 1.0 model call per question; range $0.000671 for the decline q10 to $0.001291 for q08). Actual spend $0.00: recorded on the free tier. Including our two earlier recordings: $0.023265 for all 30 calls, $0.00233 per final correct answer |
| Latency | Model call: median 7.0 s, mean 14.0 s, max 52.1 s (q01), min 0.7 s over the 10 v3 calls on the free tier (2 calls needed one retry after a 429/503 first; latency counts the successful attempt only). Replay: all 10 questions in 3.98 s wall time, startup included |
| Human time saved | 3.33 analyst hours ($400) for the 10 questions at 20 min and $120/h each; sensitivity x0.5 = 1.67 h ($200), x2 = 6.67 h ($800). Net of 5 min to review each answer's SQL: 2.5 h ($300) |
| Quality | 10 of 10 final answers match our check queries (9 answers + 1 correct decline); 7 of 10 in v1 and 7 of 10 in v2; 0 repairs and 0 budget stops in v3; two replays byte-identical |
| Cost of failure | 3 of 10 answers were silently wrong in each of v1 and v2 (valid SQL, no error, so no repair). At 20 min ($40) to redo a wrong answer once caught, 0.3 x $40 = $12 expected per question, about 13,000 times the $0.000907 model cost. One uncaught example: v2 reported Apollo's change as +$24.35B instead of +$0.85B |

## Assumptions and how each number is computed
- **Prices.** `params.yaml`: $0.30 per million input tokens and $2.50 per million output
  tokens, the paid list price for gemini-3.5-flash-lite. `usd` in every trace is
  `askpanel.econ.step_usd(tokens_in, tokens_out, 0.30, 2.50)`. Our real spend is $0 because
  we recorded on the free tier; the list price is what the same calls would cost on a paid key.
  Output tokens include any thinking tokens the API reports.
- **Cost per completed task** = v3 total usd / completed tasks = 0.009072 / 10. The cost
  including the two earlier recordings is 0.005571 (v1) + 0.008622 (v2) + 0.009072 (v3) =
  0.023265, divided by the 10 final correct answers. The prompt roughly doubled between v1
  (about 930 input tokens per call) and v3 (about 1,920), because the schema now lists the
  73 exact BDC names (the fix for Failure 1).
- **Latency** is `latency_s` in each cache entry: the wall time of the successful
  `generate_content` call, measured in record mode. Waits between retries (10 s and more) are
  not included. Free-tier latency varies widely (0.7 s to 52 s here); on a paid key we would
  expect it to be lower and steadier, but we have not measured that. The replay time is the
  wall time of `python agent/run.py --mode replay` on our laptop.
- **Human time saved.** 20 minutes per question (`economics.analyst_minutes_per_question`)
  is our estimate of the time an analyst needs to write and check the same SQL against the
  panel, or to read the schedules by hand, at $120 per hour (`economics.analyst_rate_usd`).
  The x0.5 / x2 rows come from `askpanel.econ.hours_saved_table`. The 5-minute review per
  answer is our assumption for reading the SQL the app shows next to each answer.
- **Quality** is judged question by question against our own check queries (listed in
  `outputs/failures.md`, with the two cases where our check query, not the agent, was wrong).
  Ten questions is a small sample: 0 errors in 10 is consistent with an error rate of up to
  about 30% (rule of three, 95%).
- **Cost of failure** uses the observed v1 and v2 silent-error rate (3 of 10 each) and our
  assumption that catching and redoing a wrong answer costs one full analyst task (20 min,
  $40). An uncaught wrong number reaching a portfolio decision costs far more and is not
  priced here; showing the SQL beside every answer, and the `cross_join` validator, exist to
  keep failures catchable.
