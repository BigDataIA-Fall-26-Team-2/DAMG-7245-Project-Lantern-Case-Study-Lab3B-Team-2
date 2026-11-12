import asyncio
import json
from pathlib import Path
import sys

import pytest
from mcp import Client

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from creditwatch import audit, channel
from services.mcp.errors import InvalidInputError, ScopeDeniedError
from services.mcp.handlers import read_mandate_profile
from services.mcp.server import create_server


@pytest.fixture
def dependencies():
    fixture = ROOT / "data" / "fixture"

    users = json.loads((fixture / "users.json").read_text())
    mandates = json.loads((fixture / "mandates.json").read_text())

    session = channel.login(
        "priya",
        "priya-fixture-token",
        "mandate_a",
        users,
    )

    return {
        "session": session,
        "ledger": audit.Ledger(),
        "mandates": mandates,
    }


def test_profile_returns_active_client(dependencies):
    result = read_mandate_profile(
        {"scope": "mandate_a"},
        **dependencies,
    )

    expected = dependencies["mandates"]["mandate_a"]

    assert result.client == expected["client"]
    assert result.positions == expected["positions"]
    assert set(result.model_dump()) == {"client", "positions"}
    assert dependencies["ledger"].find("tool_call")


@pytest.mark.parametrize("scope", ["mandate_b", "public"])
def test_profile_blocks_other_scopes(dependencies, scope):
    with pytest.raises(ScopeDeniedError):
        read_mandate_profile(
            {"scope": scope},
            **dependencies,
        )

    assert dependencies["ledger"].find("policy_block")
    assert not dependencies["ledger"].find("tool_call")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"scope": ""},
        {"scope": 123},
        {"scope": "mandate_a", "admin": True},
    ],
)
def test_profile_rejects_invalid_inputs(dependencies, payload):
    with pytest.raises(InvalidInputError):
        read_mandate_profile(payload, **dependencies)


def test_profile_through_mcp(dependencies):
    async def exercise():
        server = create_server(**dependencies)

        async with Client(server) as client:
            allowed = await client.call_tool(
                "mandate_profile",
                {"scope": "mandate_a"},
            )
            denied = await client.call_tool(
                "mandate_profile",
                {"scope": "mandate_b"},
            )

        assert allowed.structured_content["ok"] is True
        assert (
            allowed.structured_content["data"]["client"]
            == dependencies["mandates"]["mandate_a"]["client"]
        )

        assert denied.structured_content["ok"] is False
        assert (
            denied.structured_content["error"]["code"]
            == "SCOPE_DENIED"
        )
        assert "data" not in denied.structured_content

    asyncio.run(exercise())