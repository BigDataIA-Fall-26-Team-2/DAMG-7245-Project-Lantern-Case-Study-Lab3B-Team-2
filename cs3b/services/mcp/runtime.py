"""Session-bound tool implementations. No network or real email transport."""
import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from pydantic import ValidationError
from creditwatch import approvals, catalog, channel, clock, memory, policy, signals
from services.mcp.errors import (ToolError, ScopeDeniedError, ApprovalRequiredError,
    NotFoundError, InvalidInputError, PolicyDeniedError)
from services.mcp.schemas import INPUTS, OUTPUTS, DraftInput, WatchlistEntry
from services.signals.pairing import pair


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(value, sort_keys=True, indent=2))
    tmp.replace(path)


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


class ToolRuntime:
    def __init__(self, *, session, ledger, mandates, panel, materiality,
                 workspace, outbox, registry, canaries=None, filings=None,
                 now=clock.clock, ttl_minutes=30):
        # Copy identity so caller mutation cannot switch the running server's scope.
        self.session = channel.Session(session.principal, session.mandate)
        if session.mandate not in mandates or not re.fullmatch(r"[A-Za-z0-9_-]+", session.mandate):
            raise ScopeDeniedError("Invalid active mandate.")
        self.ledger, self.mandates = ledger, mandates
        self.panel, self.materiality = panel, materiality
        self.workspace, self.outbox = Path(workspace).resolve(), Path(outbox).resolve()
        self.registry, self.canaries, self.filings = registry, canaries or {}, filings or {}
        self.now, self.ttl_minutes = now, ttl_minutes
        self.directory = self.workspace / "mandates" / session.mandate
        self.state = self.directory / "tool_state"

    def confined(self, path, base=None):
        base = base or self.workspace
        if not path.resolve().is_relative_to(base.resolve()):
            raise PolicyDeniedError("Workspace path escapes the permitted directory.")
        return path

    def file(self, category, identifier):
        return self.confined(self.state / category / (identifier + ".json"))

    def scope(self, scope, kind="mandate"):
        try:
            channel.require_scope(self.session, scope, kind, self.ledger)
        except channel.ScopeError as exc:
            raise ScopeDeniedError("This session cannot access the requested scope.") from exc

    def private_check(self, value):
        other = policy.confidential_terms(self.mandates, self.session.mandate)
        other["terms"] += [c for m, cs in self.canaries.items() if m != self.session.mandate for c in cs]
        text = json.dumps(value, ensure_ascii=False)
        if policy.mentions(text, other["names"]) or policy.leaks(text, other["terms"]):
            raise PolicyDeniedError("R-OTHER-MANDATE: another client's confidential information.")

    def email_check(self, draft):
        self.private_check(draft)
        for recipient in draft["to"]:
            if recipient.count("@") != 1 or not recipient.rsplit("@", 1)[1].lower().endswith(".example"):
                raise PolicyDeniedError("Only fictional .example recipients are permitted.")
        others = policy.confidential_terms(self.mandates, self.session.mandate)
        rule = policy.policy_check(draft, self.mandates[self.session.mandate], self.registry, others)
        if rule:
            raise PolicyDeniedError(rule)

    def watch_check(self, entry):
        entry = WatchlistEntry.model_validate(entry).model_dump()
        if entry["bdc"] not in self.mandates[self.session.mandate]["positions"]:
            raise PolicyDeniedError("The active mandate does not hold this BDC.")
        self.private_check(entry)
        return entry

    def draft(self, draft_id):
        if not re.fullmatch(r"draft-[a-f0-9]{32}", draft_id):
            raise InvalidInputError("Invalid draft id.")
        value = read(self.file("drafts", draft_id))
        if value is None:
            raise NotFoundError("Draft not found in this session's mandate.")
        self.scope(value["scope"])
        self.email_check(value)
        return value

    def envelope(self, action, payload):
        return {"action": action, "principal": self.session.principal,
                "mandate": self.session.mandate, "payload": payload}

    def approved(self, envelope, token):
        verdict = approvals.verify_token(envelope, token, self.session.principal, self.now().timestamp())
        # A valid signature alone is insufficient: a human grant must be stored.
        key = hashlib.sha256(token.encode()).hexdigest()
        grant = read(self.file("grants", key))
        if verdict != "ok" or not grant or grant["payload_hash"] != approvals.payload_hash(envelope):
            raise ApprovalRequiredError("Exact-payload human approval is missing, changed, or expired.")

    def call(self, name, payload):
        try:
            if name not in INPUTS:
                raise NotFoundError("Unknown tool.")
            try:
                request = INPUTS[name].model_validate(payload)
            except ValidationError as exc:
                raise InvalidInputError("Arguments do not match this tool's schema.") from exc
            result = getattr(self, name)(request)
            result = OUTPUTS[name].model_validate(result).model_dump(mode="json")
            # Public filings/holdings can mention shared BDCs; private outputs must not leak clients.
            if name not in {"bdc_holdings", "bdc_signals", "get_filing"}:
                self.private_check(result)
            self.ledger.record("tool_call", tool=name, action_class=catalog.CATALOG[name][0],
                               scope=self.session.mandate, decision="executed")
            return {"ok": True, "data": result}
        except ToolError as exc:
            self.ledger.record("tool_call", tool=name, scope=self.session.mandate,
                               decision="refused", error_code=exc.code)
            return {"ok": False, "error": exc.as_dict()}
        except (OSError, ValueError, KeyError, TypeError):
            self.ledger.record("tool_call", tool=name, scope=self.session.mandate,
                               decision="failed", error_code="INTERNAL_ERROR")
            return {"ok": False, "error": {"code": "INTERNAL_ERROR", "message": "Tool could not complete; inspect local configuration."}}

    def list_mandates(self, r):
        # No enumeration of other clients in an active client's session.
        m = self.session.mandate
        return {"mandates": [{"mandate": m, "client": self.mandates[m]["client"]}]}

    def mandate_profile(self, r):
        self.scope(r.scope)
        m = self.mandates[r.scope]
        return {"client": m["client"], "positions": m["positions"]}

    def bdc_holdings(self, r):
        self.scope(r.scope, "public")
        cur = self.panel[self.panel["period_role"] == "current"]
        if r.bdc is not None:
            if r.bdc not in set(self.panel["name"]):
                raise NotFoundError("BDC not found in the panel.")
            cur = cur[cur["name"] == r.bdc]
        cols = ["adsh", "name", "identifier", "fair_value", "principal", "pik_rate", "source_rows"]
        return {"holdings": json.loads(cur[cols].to_json(orient="records"))}

    def bdc_signals(self, r):
        self.scope(r.scope, "public")
        result = signals.find_signals(self.panel, self.materiality, pair=pair)
        return {"signals": json.loads(result.to_json(orient="records"))}

    def get_filing(self, r):
        rows = self.panel[self.panel["adsh"] == r.adsh]
        meta = {}
        for cik, feed in self.filings.items():
            for i, adsh in enumerate(feed.get("accessionNumber", [])):
                if adsh == r.adsh:
                    meta = {"cik": cik, **{k: v[i] for k, v in feed.items() if isinstance(v, list) and i < len(v)}}
        if rows.empty and not meta:
            raise NotFoundError("Filing not present in the configured local data.")
        return {"adsh": r.adsh, "source": "local panel and recorded EDGAR metadata (not full filing text)",
                "rows": json.loads(rows.to_json(orient="records")), "metadata": meta}

    def watchlist_read(self, r):
        self.scope(r.scope)
        path = self.confined(self.directory / "WATCHLIST.md")
        entries = read(self.file("watchlist", "entries"), [])
        return {"text": path.read_text() if path.exists() else "", "entries": entries}

    def memory_read(self, r):
        self.scope(r.scope)
        try:
            matches = memory.read_entries(self.workspace / "mandates", r.scope, r.query, r.limit)
        except PermissionError as exc:
            raise PolicyDeniedError("Memory path escapes the active mandate.") from exc
        return {"matches": matches}

    def compact_memory(self, scope, before_day, review_hash=None):
        """Human control plane only; not an extra tool in the closed catalog."""
        self.scope(scope)
        try:
            if review_hash is None:
                result = memory.preview_compaction(self.workspace / "mandates", scope, before_day)
                self.private_check(result)
            else:
                result = memory.apply_compaction(self.workspace / "mandates", scope, before_day,
                                                 review_hash, validate=self.private_check)
                self.ledger.record("memory_compaction", scope=scope, review_hash=review_hash)
            return result
        except PermissionError as exc:
            raise PolicyDeniedError("Memory path escapes the active mandate.") from exc

    def memory_propose_write(self, r):
        self.scope(r.scope)
        self.private_check(r.content)
        pid = "prop-" + uuid4().hex
        # Tool-origin text is always a proposal, never a principal-authenticated correction.
        try:
            directory = memory.mandate_directory(self.workspace / "mandates", r.scope)
            path = memory.confined_file(directory, directory / "proposals" / (pid + ".json"))
        except PermissionError as exc:
            raise PolicyDeniedError("Proposal path escapes the active mandate.") from exc
        save(path,
             {"scope": r.scope, "content": r.content, "origin": "agent", "status": "pending"})
        self.ledger.record("proposal", proposal_id=pid, scope=r.scope, origin="agent")
        return {"proposal_id": pid, "status": "proposed"}

    def draft_email(self, r):
        self.scope(r.scope)
        draft = r.model_dump()
        self.email_check(draft)
        draft["draft_id"] = "draft-" + uuid4().hex
        save(self.file("drafts", draft["draft_id"]), draft)
        return draft

    def request_approval(self, r):
        try:
            if r.action == "send_email":
                if set(r.payload) != {"draft_id"}:
                    raise InvalidInputError("Send approval requires only draft_id.")
                payload = self.draft(r.payload["draft_id"])
            else:
                if set(r.payload) != {"scope", "entry"}:
                    raise InvalidInputError("Watchlist approval requires scope and entry.")
                self.scope(r.payload["scope"])
                payload = {"scope": r.payload["scope"], "entry": self.watch_check(r.payload["entry"])}
        except ValidationError as exc:
            raise InvalidInputError("Invalid approval payload.") from exc
        envelope = self.envelope(r.action, payload)
        rid = "req-" + uuid4().hex
        save(self.file("requests", rid), {"request_id": rid, "envelope": envelope, "status": "pending"})
        self.ledger.record("approval_requested", request_id=rid, payload_hash=approvals.payload_hash(envelope))
        return {"request_id": rid, "payload_hash": approvals.payload_hash(envelope), "status": "pending"}

    def grant(self, request_id, confirmation):
        """Human control plane only. Deliberately absent from the MCP catalog."""
        if not re.fullmatch(r"req-[a-f0-9]{32}", request_id):
            raise InvalidInputError("Invalid request id.")
        req = read(self.file("requests", request_id))
        if not req:
            raise NotFoundError("Approval request not found.")
        envelope = req["envelope"]
        digest = approvals.payload_hash(envelope)
        if confirmation != digest or envelope["principal"] != self.session.principal or envelope["mandate"] != self.session.mandate:
            raise ScopeDeniedError("Approval must confirm the exact payload in this session.")
        token = approvals.issue_token(envelope, self.session.principal, self.now().timestamp(), self.ttl_minutes)
        save(self.file("grants", hashlib.sha256(token.encode()).hexdigest()), {"payload_hash": digest, "request_id": request_id})
        self.ledger.record("approval_granted", request_id=request_id, payload_hash=digest)
        return token

    def send_email(self, r):
        self.scope(r.scope)
        draft = self.draft(r.draft_id)
        envelope = self.envelope("send_email", draft)
        self.approved(envelope, r.approval_token)
        digest = approvals.payload_hash(envelope)
        mid = "msg-" + digest
        path = self.confined(self.outbox / (mid + ".json"), self.outbox)
        if path.exists():
            return {"outbox_message_id": mid, "status": "already_sent"}
        save(path, {"message_id": mid, **draft})
        self.ledger.record("mock_send", message_id=mid, payload_hash=digest, scope=r.scope)
        return {"outbox_message_id": mid, "status": "sent"}

    def watchlist_write(self, r):
        self.scope(r.scope)
        entry = self.watch_check(r.entry.model_dump())
        payload = {"scope": r.scope, "entry": entry}
        envelope = self.envelope("watchlist_write", payload)
        self.approved(envelope, r.approval_token)
        eid = "watch-" + approvals.payload_hash(envelope)
        path = self.file("watchlist", "entries")
        entries = read(path, [])
        exists = any(e["watchlist_entry_id"] == eid for e in entries)
        if not exists:
            entries.append({"watchlist_entry_id": eid, **entry})
            save(path, entries)
        # Rebuild only our managed section; preserve the student's original notes.
        md = self.confined(self.directory / "WATCHLIST.md")
        marker = "\n<!-- MCP-managed entries -->\n"
        original = md.read_text() if md.exists() else "# Watchlist\n"
        base = original.split(marker)[0]
        def clean(s):
            return s.replace("\n", " ").replace("\r", " ").replace("<", "&lt;")
        lines = ["- " + clean(e["bdc"]) + ": " + clean(e["note"]) + " [" + "; ".join(clean(c) for c in e["citations"]) + "]" for e in entries]
        md.write_text(base + marker + "\n".join(lines) + "\n")
        return {"watchlist_entry_id": eid, "status": "already_written" if exists else "written"}
