"""Synchronous MCP tool calls for the agent and the app (Lab 34B).

The agent's nodes are plain synchronous functions; the MCP SDK v2 Client is async.
PanelClient keeps one Client session open on a private event loop in a background
thread and hands out blocking calls. It speaks to the server only over the MCP
protocol (in memory, Client(server.mcp)): nothing here touches the database.
"""
import asyncio
import logging
import re
import threading

from agent import ROOT  # noqa: F401  (puts cs4b/ and src/ on sys.path)
from mcp import Client

# refusals are expected observations, not crashes: keep the SDK's INFO lines quiet
logging.getLogger("mcp").setLevel(logging.WARNING)

_PREFIX = re.compile(r"^Error executing tool \w+:\s*")
_CODE = re.compile(r"^([a-z_]+):\s*(.*)$", re.S)


class ToolCallError(Exception):
    """A tool call the server refused. code is the gate's code (not_select, ...)."""

    def __init__(self, code, detail):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def _error(text):
    text = _PREFIX.sub("", text or "").strip()
    m = _CODE.match(text)
    return ToolCallError(m.group(1), m.group(2)) if m else ToolCallError("tool_error", text)


class PanelClient:
    def __init__(self, server=None):
        if server is None:
            from services.mcp import server as server_module
            server = server_module.mcp
        self._server = server
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True,
                                        name="mcp-client")
        self._thread.start()
        self._client = None
        self._ready = threading.Event()
        self._stop = None
        # one long-lived task owns the session: anyio needs it entered and exited in the same task
        self._main = asyncio.run_coroutine_threadsafe(self._hold(), self._loop)
        if not self._ready.wait(30):
            raise RuntimeError("MCP client did not connect")
        if self._main.done():
            self._main.result()                        # re-raise a connection error

    async def _hold(self):
        self._stop = asyncio.Event()
        try:
            async with Client(self._server) as c:
                self._client = c
                self._ready.set()
                await self._stop.wait()
        finally:
            self._client = None
            self._ready.set()

    def _run(self, coro, timeout=60):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def list_tool_names(self):
        return [t.name for t in self._run(self._client.list_tools()).tools]

    def call(self, tool, **args):
        """structured_content of one tool call, or raise ToolCallError."""
        r = self._run(self._client.call_tool(tool, args))
        if r.is_error:
            raise _error(r.content[0].text if r.content else "")
        return r.structured_content

    # the four tools, in the shapes askpanel.nodes expects
    def list_tables(self):
        return self.call("list_tables")["tables"]

    def describe_table(self, table):
        return self.call("describe_table", table=table)["columns"]

    def sample_values(self, table, column, limit=20):
        return self.call("sample_values", table=table, column=column, limit=limit)["values"]

    def run_query(self, sql):
        return self.call("run_query", sql=sql)

    def tools(self):
        return {"list_tables": self.list_tables, "describe_table": self.describe_table,
                "sample_values": self.sample_values, "run_query": self.run_query}

    def close(self):
        if self._loop.is_running():
            try:
                if self._stop is not None:
                    self._loop.call_soon_threadsafe(self._stop.set)
                    self._main.result(10)
            finally:
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._thread.join(timeout=5)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
