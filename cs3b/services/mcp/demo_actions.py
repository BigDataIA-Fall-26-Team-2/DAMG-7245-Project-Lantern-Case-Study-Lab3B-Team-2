"""Simulated approval exercise: local mock outbox only, isolated agent workspace."""
import json
from pathlib import Path
from uuid import uuid4
from services.mcp.server import ROOT, create_runtime
from services.mcp.runtime import read, save
from creditwatch import audit, channel, clock, workspace


def run(root=ROOT):
    root = Path(root)
    run_id = "lab29-actions-" + uuid4().hex
    scratch = root / ".cache" / run_id
    ws = workspace.fresh_workspace(root / "agent_seed", scratch / "agent")
    fx = root / "data/fixture"
    users = json.loads((fx / "users.json").read_text())
    mandates = json.loads((fx / "mandates.json").read_text())
    log_path = root / "logs/audit" / (run_id + ".jsonl")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    r = create_runtime(session=channel.login("priya", "priya-fixture-token", "mandate_a", users),
                       ledger=audit.Ledger(log_path, clock=clock.clock), mandates=mandates,
                       root=root, workspace=ws, outbox=root / "outputs/outbox")
    def call(name, args):
        result = r.call(name, args)
        assert result["ok"], result
        return result["data"]
    draft = call("draft_email", {"scope": "mandate_a", "to": [mandates["mandate_a"]["contacts"][0]],
        "subject": "Lab 29 fictional approval exercise", "body": "Local test message only.", "attachments": []})
    request = call("request_approval", {"action": "send_email", "payload": {"draft_id": draft["draft_id"]}})
    # Simulate the human control plane in this test; this is NOT real human consent.
    token = r.grant(request["request_id"], request["payload_hash"])
    draft["to"].append(mandates["mandate_a"]["contacts"][1])
    save(r.file("drafts", draft["draft_id"]), draft)
    args = {"scope": "mandate_a", "draft_id": draft["draft_id"], "approval_token": token}
    denied = r.call("send_email", args)
    assert denied["error"]["code"] == "APPROVAL_REQUIRED"
    request = call("request_approval", {"action": "send_email", "payload": {"draft_id": draft["draft_id"]}})
    args["approval_token"] = r.grant(request["request_id"], request["payload_hash"])
    sent = call("send_email", args)
    duplicate = call("send_email", args)
    stored = read(r.outbox / (sent["outbox_message_id"] + ".json"))
    assert stored["to"] == draft["to"] and duplicate["status"] == "already_sent"
    # Exercise a correctly approved internal write in the scratch mandate only.
    payload = {"scope": "mandate_a", "entry": {"bdc": "FIXTURE HOTEL SENIOR LENDING",
               "note": "Review Brightwater markdown evidence.", "citations": ["0009000012-26-000121#101"]}}
    watch_request = call("request_approval", {"action": "watchlist_write", "payload": payload})
    watch_token = r.grant(watch_request["request_id"], watch_request["payload_hash"])
    watch = call("watchlist_write", {**payload, "approval_token": watch_token})
    report = {"run_id": run_id, "mode": "fixture exercise with simulated human approvals; no external email",
              "blocked_reason": r.ledger.find("policy_block")[-1]["reason"],
              "approved_send": sent, "retry_status": duplicate["status"], "watchlist_write": watch,
              "audit_log": str(log_path.relative_to(root)),
              "outbox_file": str((r.outbox / (sent["outbox_message_id"] + ".json")).relative_to(root)),
              "scratch_workspace": str(ws.relative_to(root))}
    destination = root / "reports/actions" / (run_id + ".json")
    save(destination, report)
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    run()
