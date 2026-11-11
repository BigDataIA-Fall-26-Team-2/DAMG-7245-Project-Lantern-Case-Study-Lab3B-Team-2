---
name: bdc-quarter-review
description: Review one BDC filing with paired-period signals, coverage and citations.
---
# Quarterly review

Use for a review of one BDC, rather than a client-wide monthly note.

1. Read `bdc_holdings` and `bdc_signals` with scope `public`; filter by the exact BDC name.
   The MCP data are under `data.holdings` and `data.signals` respectively.
2. Use `get_filing(adsh=...)` for local filing rows and metadata. Compare current and
   prior-year-end schedules within the same filing. Do not pair different filings.
3. State total debt holdings, paired count, and unpaired count when the pairing output
   supplies them. A signal count is not a pairing count. If coverage is unavailable,
   label it unavailable; never imply that all holdings were checked.
4. Save the filtered signals as a JSON list and run from this skill folder:
   `python scripts/signal_table.py signals.json`.
   Use the generated table instead of retyping values. It includes both row references.
5. Explain material changes with accession, current row and prior row. Markdown
   differences are points, PIK changes are percentage points, and maturity extensions
   compare dates. PIK present at origination alone is not deterioration.
6. Finish with unresolved evidence and follow-up questions. A result with no signals
   means no detected qualifying changes, not proof of no credit risk.

Deliver a review headed by BDC and accession, coverage, evidence table, then a short
assessment. For a client-directed draft, apply the active mandate's holdings filter;
use `draft_email` and request exact-payload approval before any mock send.
