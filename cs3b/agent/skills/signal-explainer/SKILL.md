---
name: signal-explainer
description: Explain a markdown, PIK increase or maturity extension using cited row values.
---
# Signal explanation

Use to explain a detected change; do not use it to invent signals for an unmatched
holding or independently classify a borrower as distressed.

1. Read `bdc_signals(scope="public")`, then select the requested signal using BDC,
   accession, rule and row references. For a client response, confirm that the
   active mandate holds the BDC. Use `get_filing` for available supporting rows.
2. Save selected `data.signals` as a JSON list. From this skill folder run:
   `python scripts/explain_signals.py signals.json`.
   The script checks supported rules and value direction, calculates differences,
   escapes table delimiters, and prints deterministic cited explanations.
3. MARKDOWN is the before/after value difference in points, not a relative percent
   return. PIK_UP is a rate increase in percentage points. EXTENDED compares ISO
   maturity dates and reports elapsed days, not an assumed number of whole months.
4. Explain the possible significance separately from the measured change. A higher
   PIK rate is not by itself proof of distress; PIK at origination is not a new
   increase. An extension does not prove default or a concession.
5. Retain accession, current row and prior row in the answer. If values, dates or
   evidence references are missing, report insufficient evidence rather than filling
   gaps. The helper formats supplied evidence; it does not verify filing authenticity.

Return a cited observation, a qualified interpretation and any missing evidence.
Drafting this explanation grants no permission to send it or update a watchlist.
