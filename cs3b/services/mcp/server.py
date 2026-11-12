"""The twelve-tool MCP server. Launch from cs3b with python -m services.mcp.server."""
import argparse
from getpass import getpass
import json
import os
from pathlib import Path
import sys
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
import yaml
from mcp.server import MCPServer
from creditwatch import audit, catalog, channel, clock, panel as panel_module
from services.mcp.runtime import ToolRuntime
from services.mcp.schemas import WatchlistEntry

REGISTRY = {
    "list_mandates": "READ", "bdc_holdings": "READ", "bdc_signals": "READ",
    "get_filing": "READ", "mandate_profile": "READ", "watchlist_read": "READ",
    "memory_read": "READ", "memory_propose_write": "INTERNAL_WRITE",
    "watchlist_write": "INTERNAL_WRITE", "draft_email": "DRAFT",
    "request_approval": "CONTROL", "send_email": "EXTERNAL_SEND",
}


def create_runtime(*, session, ledger, mandates, root=ROOT, panel=None,
                   materiality=None, workspace=None, outbox=None, registry=None,
                   canaries=None, filings=None, now=clock.clock, ttl_minutes=None):
    root = Path(root)
    settings = yaml.safe_load((root / "params.yaml").read_text())
    fx = root / settings["data"]["fixture_dir"]
    return ToolRuntime(
        session=session, ledger=ledger, mandates=mandates,
        panel=panel if panel is not None else panel_module.load_panel(root / settings["data"]["panel"]),
        materiality=materiality if materiality is not None else settings["heartbeat"]["materiality"],
        workspace=workspace or root / settings["agent"]["workspace"],
        outbox=outbox or root / "outputs/outbox",
        registry=registry if registry is not None else json.loads((root / settings["data"]["registry"]).read_text()),
        canaries=canaries if canaries is not None else json.loads((fx / "canaries.json").read_text()),
        filings=filings if filings is not None else json.loads((fx / "edgar_recent.json").read_text()),
        now=now, ttl_minutes=ttl_minutes if ttl_minutes is not None else settings["approvals"]["ttl_minutes"],
        action_policy=settings["action_policy"], principal=settings["agent"]["principal"],
    )


def create_server(*, session=None, ledger=None, mandates=None, runtime=None, **options):
    runtime = runtime or create_runtime(session=session, ledger=ledger, mandates=mandates, **options)
    server = MCPServer("creditwatch-tools")

    @server.tool()
    def list_mandates() -> dict[str, Any]:
        """List only the active mandate (READ)."""
        return runtime.call("list_mandates", {})

    @server.tool()
    def bdc_holdings(scope: str, bdc: str | None = None) -> dict[str, Any]:
        """Read current public holdings, optionally filtered by exact BDC name (READ)."""
        return runtime.call("bdc_holdings", {"scope": scope, "bdc": bdc})

    @server.tool()
    def bdc_signals(scope: str) -> dict[str, Any]:
        """Read public within-filing credit signals with row evidence (READ)."""
        return runtime.call("bdc_signals", {"scope": scope})

    @server.tool()
    def get_filing(adsh: str) -> dict[str, Any]:
        """Read locally recorded filing rows and metadata by accession; not full SEC text (READ)."""
        return runtime.call("get_filing", {"adsh": adsh})

    @server.tool()
    def mandate_profile(scope: str) -> dict[str, Any]:
        """Read the active client name and positions (READ)."""
        return runtime.call("mandate_profile", {"scope": scope})

    @server.tool()
    def watchlist_read(scope: str) -> dict[str, Any]:
        """Read the active mandate watchlist (READ)."""
        return runtime.call("watchlist_read", {"scope": scope})

    @server.tool()
    def memory_read(scope: str, query: str = "", limit: int = 5) -> dict[str, Any]:
        """Search active-mandate memory and logs with source references (READ)."""
        return runtime.call("memory_read", {"scope": scope, "query": query, "limit": limit})

    @server.tool()
    def memory_propose_write(scope: str, content: str) -> dict[str, Any]:
        """Propose agent-origin memory; never change principal rules (INTERNAL_WRITE)."""
        return runtime.call("memory_propose_write", {"scope": scope, "content": content})

    @server.tool()
    def watchlist_write(scope: str, entry: WatchlistEntry, approval_token: str = "") -> dict[str, Any]:
        """Write an exact human-approved watchlist entry (INTERNAL_WRITE)."""
        return runtime.call("watchlist_write", {"scope": scope, "entry": entry.model_dump(), "approval_token": approval_token})

    @server.tool()
    def draft_email(scope: str, to: list[str], subject: str, body: str, attachments: list[str] | None = None) -> dict[str, Any]:
        """Store a policy-checked fictional email draft; does not send (DRAFT)."""
        return runtime.call("draft_email", {"scope": scope, "to": to, "subject": subject, "body": body, "attachments": attachments or []})

    @server.tool()
    def request_approval(action: Literal["send_email", "watchlist_write"], payload: dict[str, Any]) -> dict[str, Any]:
        """Create a pending request for exact-payload human approval; does not grant it (CONTROL)."""
        return runtime.call("request_approval", {"action": action, "payload": payload})

    @server.tool()
    def send_email(scope: str, draft_id: str, approval_token: str = "") -> dict[str, Any]:
        """Send an approved draft only to the local mock outbox (EXTERNAL_SEND)."""
        return runtime.call("send_email", {"scope": scope, "draft_id": draft_id, "approval_token": approval_token})

    assert catalog.conformance(REGISTRY) == []
    return server


def authenticated_runtime(root, mandate, token):
    root = Path(root).resolve()
    settings = yaml.safe_load((root / "params.yaml").read_text())
    users = json.loads((root / settings["data"]["fixture_dir"] / "users.json").read_text())
    session = channel.login(settings["agent"]["principal"], token, mandate, users)
    mandates = json.loads((root / settings["data"]["mandates"]).read_text())
    logdir = root / "logs/audit"
    logdir.mkdir(parents=True, exist_ok=True)
    from uuid import uuid4
    ledger = audit.Ledger(logdir / ("mcp-" + uuid4().hex + ".jsonl"), clock=clock.clock)
    return create_runtime(session=session, ledger=ledger, mandates=mandates, root=root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--mandate", default="mandate_a")
    args = parser.parse_args()
    token = os.environ.get("CREDITWATCH_SESSION_TOKEN") or getpass("Priya session token: ")
    runtime = authenticated_runtime(args.root, args.mandate, token)
    create_server(runtime=runtime).run()


if __name__ == "__main__":
    main()
