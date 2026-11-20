# EC2 demo release

The production React build is served by nginx. `/api/` proxies to one Uvicorn
worker on localhost; the agent reaches SQLite only through MCP. Use Ubuntu 24.04
(Python 3.12), a `t3.small`, an 8 GiB encrypted gp3 root disk, and standard CPU
credits. The pinned NumPy requires Python 3.12+, despite the original kit's
Python 3.11 claim. Do not run Vite's development server in production.

## Install

1. Build `frontend/` with `npm ci && npm run build` (Node 22 recommended).
2. Copy the release's `cs4b/` and built `frontend/dist/` to `/opt/askpanel/cs4b/`.
   Exclude `.env`, local virtual environments, `node_modules`, logs and local databases.
3. Run `sudo bash /opt/askpanel/cs4b/deploy/install.sh`. This builds the database
   from the real panel and installs nginx and the systemd service.
4. Put `GEMINI_API_KEY=...` in `/etc/askpanel.env` (root owned, mode 600) through
   SSH, never in Git, EC2 user-data, frontend variables or shell command arguments.
   Run `sudo systemctl restart askpanel`.
5. Check `/api/health`, recorded questions, the q02/q03 follow-up, and one live query.
   Service logs: `sudo journalctl -u askpanel`; audit: `cs4b/logs/server_ledger.jsonl`.

## Access and costs

No Elastic IP, load balancer, NAT gateway or paid domain is required. EC2 gets an
ordinary public IP, which can change after stop/start. Restrict security group
ports 22 and 80 to the demo owner's current public IP (/32); port 8000 is not
exposed. Update that allowlist if your network changes. HTTP is suitable only for
this restricted demo with public panel data; add HTTPS and authentication before
opening access broadly. Live mode uses the server's Gemini key.

An EC2 instance, EBS disk and public IPv4 are billable resources; account credits
must cover them. The owner confirmed available credits before this deployment;
the lantern IAM profile cannot inspect Free Tier billing. Stop the instance when
finished; storage remains billable until termination/deletion. The root disk is
configured to delete on termination. Gemini billing is separate from AWS credits.

Conversation history is in memory and resets when the process restarts. Live
responses and audit logs persist on the root disk. A single worker is intentional
because threads/checkpoints are process-local.

## Release verification

- Combined agent/server/API suite: 96 passed on Python 3.13.
- Assignment self-check: 12/12; ten questions replay twice byte-identically.
- Frontend TypeScript + production build passed; npm audit: zero findings.
- Database reset regression: calling server.configure() restores the configured
  default after fixture tests rather than leaving the API pointed at fixture data.
- Browser checks cover recorded answers, follow-ups, cache errors and mobile layout.
