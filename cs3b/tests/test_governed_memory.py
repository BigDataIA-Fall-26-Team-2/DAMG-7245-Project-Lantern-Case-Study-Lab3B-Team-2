"""Lab 27: isolation AND useful recall, across fresh sessions and MCP clients."""
import asyncio
import json
from pathlib import Path
import sys

import pytest
from mcp import Client
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from creditwatch import audit, channel, evals, memory, workspace
from creditwatch.chat import Harness
from services.mcp.server import create_runtime, create_server
from services.mcp.errors import ScopeDeniedError, PolicyDeniedError


@pytest.fixture
def setup(tmp_path):
    (tmp_path / "params.yaml").write_text((ROOT / "params.yaml").read_text())
    (tmp_path / "data").symlink_to(ROOT / "data", target_is_directory=True)
    ws = workspace.fresh_workspace(ROOT / "agent_seed", tmp_path / "agent")
    for scope in ("mandate_a", "mandate_b"):
        (ws / "mandates" / scope / "MEMORY.md").write_text("# Memory\n")
    fx = ROOT / "data/fixture"
    users = json.loads((fx / "users.json").read_text())
    mandates = json.loads((fx / "mandates.json").read_text())
    canaries = json.loads((fx / "canaries.json").read_text())
    def runtime(scope):
        return create_runtime(session=channel.login("priya", "priya-fixture-token", scope, users),
            ledger=audit.Ledger(), mandates=mandates, workspace=ws, outbox=tmp_path / "outbox")
    return tmp_path, ws, runtime, canaries


@pytest.mark.parametrize("active,other", [("mandate_a", "mandate_b"), ("mandate_b", "mandate_a")])
def test_recall_and_canaries_across_sessions_and_compaction(setup, active, other):
    root, ws, runtime, canaries = setup
    fact = "Remember the meeting reference Sapphire at 09:15 next Thursday."
    ref = memory.append_log(ws / "mandates", active, "2026-10-13", fact)
    memory.append_log(ws / "mandates", other, "2026-10-13", "Private " + canaries[other][0])
    first = runtime(active)
    before = (ws / "mandates" / active / "MEMORY.md").read_text()
    plan = first.compact_memory(active, "2026-10-15")
    assert (ws / "mandates" / active / "MEMORY.md").read_text() == before
    assert fact in plan["text"] and ref in plan["text"]
    assert not evals.canary_hits([plan["text"], plan["diff"]], canaries[other])
    first.compact_memory(active, "2026-10-15", plan["review_hash"])
    assert first.ledger.find("memory_compaction", scope=active)
    assert fact in (ws / "mandates" / active / "log/2026-10-13.md").read_text()
    assert runtime(active).compact_memory(active, "2026-10-15")["diff"] == ""
    # New runtime and authenticated chat objects: nothing relies on process memory.
    fresh = runtime(active)
    result = fresh.call("memory_read", {"scope": active, "query": "Sapphire"})
    assert result["ok"] and fact in json.dumps(result)
    assert not evals.canary_hits([json.dumps(result)], canaries[other])
    context = Harness(root).login("priya", "priya-fixture-token", active).context
    assert fact in context
    assert not evals.canary_hits([context], canaries[other])
    own = runtime(other).call("memory_read", {"scope": other, "query": "Private"})
    assert evals.canary_hits([json.dumps(own, ensure_ascii=False)], canaries[other])
    wrong = fresh.call("memory_read", {"scope": other, "query": "Private"})
    assert wrong["error"]["code"] == "SCOPE_DENIED" and "data" not in wrong
    with pytest.raises(ScopeDeniedError):
        fresh.compact_memory(other, "2026-10-15")


@pytest.mark.parametrize("active,other", [("mandate_a", "mandate_b"), ("mandate_b", "mandate_a")])
def test_memory_contracts_through_mcp(setup, active, other):
    _, ws, runtime, canaries = setup
    memory.append_log(ws / "mandates", active, "2026-10-13", "Recall Violet meeting")
    principal = (ws / "PRINCIPAL.md").read_bytes()
    async def exercise():
        async with Client(create_server(runtime=runtime(active))) as client:
            read = await client.call_tool("memory_read", {"scope": active, "query": "Violet"})
            assert read.structured_content["data"]["matches"]
            assert not evals.canary_hits([json.dumps(read.structured_content)], canaries[other])
            proposal = await client.call_tool("memory_propose_write", {"scope": active, "content": "Prefer short notes"})
            assert proposal.structured_content["data"]["status"] == "proposed"
            for tool, extra in [("memory_read", {}), ("memory_propose_write", {"content": "Wrong client"})]:
                denied = await client.call_tool(tool, {"scope": other, **extra})
                assert denied.structured_content["error"]["code"] == "SCOPE_DENIED"
    asyncio.run(exercise())
    assert (ws / "PRINCIPAL.md").read_bytes() == principal
    proposals = list((ws / "mandates" / active / "proposals").glob("*.json"))
    assert len(proposals) == 1
    assert json.loads(proposals[0].read_text())["origin"] == "agent"
    # Proposals are not active memory or context.
    assert "Prefer short notes" not in memory.context_memory(ws / "mandates", active)


def test_stale_diff_rejected_and_full_fact_retained(setup):
    _, ws, runtime, _ = setup
    r = runtime("mandate_a")
    fact = "Long evidence " + "detail " * 30 + "critical ending: 72.6"
    memory.append_log(ws / "mandates", "mandate_a", "2026-10-13", fact)
    plan = r.compact_memory("mandate_a", "2026-10-15")
    old = (r.directory / "MEMORY.md").read_bytes()
    memory.append_log(ws / "mandates", "mandate_a", "2026-10-13", "Later observation")
    with pytest.raises(ValueError, match="changed"):
        r.compact_memory("mandate_a", "2026-10-15", plan["review_hash"])
    assert (r.directory / "MEMORY.md").read_bytes() == old
    plan = r.compact_memory("mandate_a", "2026-10-15")
    r.compact_memory("mandate_a", "2026-10-15", plan["review_hash"])
    assert fact in (r.directory / "MEMORY.md").read_text()


def test_cutoff_and_curated_memory_preserved(setup):
    _, ws, runtime, _ = setup
    r = runtime("mandate_a")
    (r.directory / "MEMORY.md").write_text("# Memory\nCurated existing fact\n")
    memory.append_log(ws / "mandates", "mandate_a", "2026-10-15", "Cutoff day event")
    plan = r.compact_memory("mandate_a", "2026-10-15")
    assert "Curated existing fact" in plan["text"]
    assert "Cutoff day event" not in plan["text"]
    assert "Cutoff day event" in json.dumps(r.call("memory_read", {"scope": "mandate_a", "query": "Cutoff"}))


@pytest.mark.parametrize("surface", ["read", "compact", "context"])
def test_contaminated_memory_is_blocked(setup, surface):
    root, ws, runtime, canaries = setup
    # A known B canary copied into A is still blocked, including zero-width text.
    poison = canaries["mandate_b"][0].replace("-", "\u200b-")
    (ws / "mandates/mandate_a/MEMORY.md").write_text(poison)
    r = runtime("mandate_a")
    if surface == "read":
        result = r.call("memory_read", {"scope": "mandate_a"})
        assert result["error"]["code"] == "POLICY_DENIED" and "data" not in result
    elif surface == "compact":
        with pytest.raises(PolicyDeniedError):
            r.compact_memory("mandate_a", "2026-10-15")
    else:
        with pytest.raises(PermissionError):
            Harness(root).login("priya", "priya-fixture-token", "mandate_a")


def test_symlink_cannot_redirect_memory_to_other_mandate(setup):
    root, ws, runtime, _ = setup
    path = ws / "mandates/mandate_a/MEMORY.md"
    path.unlink()
    path.symlink_to(ws / "mandates/mandate_b/MEMORY.md")
    assert runtime("mandate_a").call("memory_read", {"scope": "mandate_a"})["error"]["code"] == "POLICY_DENIED"
    with pytest.raises(PolicyDeniedError):
        runtime("mandate_a").compact_memory("mandate_a", "2026-10-15")
    with pytest.raises(PermissionError):
        Harness(root).login("priya", "priya-fixture-token", "mandate_a")
