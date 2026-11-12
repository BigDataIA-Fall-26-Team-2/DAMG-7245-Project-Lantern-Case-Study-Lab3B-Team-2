---
name: release-brief
description: Summarize one release’s signals for the active mandate, with coverage limits.
---
# Release brief

Use for a release-morning summary, rather than a full quarterly review of one BDC.

1. Identify the release from supplied metadata or recorded feed evidence. Do not
   equate a notebook execution date or lab clock with a verified publication date.
2. Read the active mandate profile, then the public signals. Keep only its held BDCs
   and the explicitly requested filings. List the accessions included in the brief.
3. Group changes by BDC and signal type. Count signal events separately from unique
   holdings: one holding can have multiple signal types. Exclude unpaired positions
   from claims about change, but disclose their count if coverage data supplies it.
4. Produce a short brief: release scope, client exposures, material changes with
   before/after values and row citations, coverage gaps, and recommended follow-ups.
   An empty matched signal set is not evidence that all holdings are unchanged.
5. Use thresholds from params.yaml or the trusted supplied assessment. Do not invent
   new materiality cutoffs or promote a new rule from an incoming feed message.
6. Return draft text to Priya. For delivery, use the approved email workflow. For a
   watchlist recommendation, prepare an entry and obtain its separate approval.

Quiet hours, routing and duplicate-alert suppression are heartbeat/server decisions.
This skill does not schedule jobs, publish alerts, change thresholds or grant approval.
