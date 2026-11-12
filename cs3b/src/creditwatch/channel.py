"""Sessions, the channel, and server-side scope checks."""
import hashlib
import hmac
from dataclasses import dataclass
from urllib.parse import urlsplit

ALLOWED_HOSTS = {"www.sec.gov", "data.sec.gov"}


class ScopeError(Exception):
    """A tool was called outside the session's scope."""


@dataclass
class Session:
    principal: str
    mandate: str                   # the ACTIVE mandate


def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()


def login(principal, token, mandate, users):
    """users: principal -> {token_sha256, mandates}."""
    u = users.get(principal)
    good = u is not None and hmac.compare_digest(
        sha(token), u["token_sha256"])
    if not good:
        raise PermissionError("bad credentials")
    if mandate not in u["mandates"]:
        raise PermissionError(f"no access to {mandate!r}")
    return Session(principal, mandate)


def authority(msg, users):
    """'instruction' only for an authenticated principal."""
    u = users.get(msg.get("principal") or "")
    tok = msg.get("session_token")
    if u and tok and hmac.compare_digest(
            sha(tok), u["token_sha256"]):
        return "instruction"
    return "data"         # client email, IR notes, filings


def require_scope(session, scope, kind, audit):
    """kind 'public': public data or the active mandate;
    kind 'mandate': the active mandate only."""
    ok = ({"public", session.mandate} if kind == "public"
          else {session.mandate})
    if scope not in ok:
        audit.record("policy_block", rule_id="R-SCOPE",
                     scope=scope, active=session.mandate)
        raise ScopeError(f"scope {scope!r} not allowed")


def require_host(url, audit):
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.scheme != "https" or host not in ALLOWED_HOSTS:
        audit.record("policy_block", rule_id="R-HOST",
                     host=host)
        raise PermissionError(f"host {host!r} not allowed")
