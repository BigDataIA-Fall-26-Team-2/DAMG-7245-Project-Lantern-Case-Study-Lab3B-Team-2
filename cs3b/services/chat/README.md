# Part 0: authenticated chat harness

Run notebook 00 first. From the project root with `.venv` activated:

```bash
PYTHONPATH=src python -m creditwatch.chat --mandate mandate_a
```

Enter the supplied fictional fixture token `priya-fixture-token` when prompted.
The terminal hides your token. Try `/session`, `/context`, `/help`, and `/quit`.
For mandate B, start a new CLI session with `--mandate mandate_b`.

For the web interface:

```bash
python services/chat/web.py
```

Open http://127.0.0.1:8000, select a mandate, and enter the same fixture token.
Log out before changing mandates. Stop the server with Ctrl+C.

Both interfaces use `channel.login` and the same context assembly code in
`src/creditwatch/chat.py`. The web session uses an opaque HttpOnly cookie and
expires after one hour. Tokens are not stored in browser storage or chat logs.
This is a loopback-only classroom server with fictional credentials, not a
production authentication service.

This stage supports context inspection and acknowledges ordinary messages.
It does not yet call an LLM, execute tools, send emails, or update watchlists.
Those capabilities belong to later labs. Incoming email data must not be
submitted as authenticated principal instructions when those tools are added.

Run the Part 0 acceptance tests and starter tests:

```bash
python -m pytest -q
```

`tests/test_chat.py` covers failed authentication, unauthorized mandates,
context isolation in both directions, fixed session scope, web login and logout,
and rejection of cross-origin requests. `tests/run_tests.py` runs only the
original starter test module; use pytest to include the new tests.
