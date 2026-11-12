---
name: watchlist-entry
description: Prepare an evidence-backed watchlist entry for an active-client holding.
---
# Watchlist entry

Use to prepare or add one monitored issue for a BDC held by the active client.

1. Read the active mandate profile and watchlist. Confirm the BDC is held and inspect
   existing entries before proposing another entry for the same evidence.
2. Read the relevant public signals and local filing rows. Keep the triggering
   observation distinct from a proposed action. Cite the accession and both row IDs.
3. Prepare `entry` with exactly `bdc`, `note`, and `citations` (a nonempty string list).
   `bdc` must be the exact held name. Keep the note focused on what changed, why it
   warrants attention, and what evidence should be checked next. Do not invent a
   rating, borrower status, review date, owner or coverage percentage.
4. Show Priya the proposed entry. Request approval with action `watchlist_write`
   and payload `{"scope": active_mandate, "entry": entry}`.
5. After human approval, call `watchlist_write` with the identical scope, entry and
   issued approval token. If the wording or citations change, request new approval.
6. Read the watchlist again and report its returned entry ID. A pending request is
   not a completed write. This tool appends managed entries; it does not edit or
   delete old entries. Escalate an unsupported update rather than overwriting files.

Watchlist edits require approval even though they are classified INTERNAL_WRITE:
clients rely on the information. Never bypass that requirement with direct file edits.
