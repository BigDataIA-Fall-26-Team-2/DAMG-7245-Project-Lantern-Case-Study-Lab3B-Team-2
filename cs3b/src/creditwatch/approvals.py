"""Approval bound to the exact payload (HMAC token)."""
import hashlib
import hmac
import json
import os


def secret():
    return os.environ.get("CREDITWATCH_APPROVAL_SECRET",
                          "replay-only-test-secret").encode()


def payload_hash(payload):
    """Every field of the stored draft except its id."""
    keep = {k: v for k, v in payload.items() if k != "draft_id"}
    canon = json.dumps(keep, sort_keys=True,
                       separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def issue_token(payload, approver, now, ttl_min=30):
    exp = int(now + ttl_min * 60)
    msg = f"{payload_hash(payload)}|{approver}|{exp}".encode()
    sig = hmac.new(secret(), msg, hashlib.sha256).hexdigest()
    return f"{approver}.{exp}.{sig}"


def verify_token(payload, token, principal, now):
    try:
        approver, exp, sig = token.rsplit(".", 2)
        exp = int(exp)
    except (AttributeError, ValueError):
        return "malformed"
    if approver != principal:
        return "wrong_approver"
    if now >= exp:
        return "expired"
    msg = f"{payload_hash(payload)}|{approver}|{exp}".encode()
    good = hmac.new(secret(), msg, hashlib.sha256).hexdigest()
    return ("ok" if hmac.compare_digest(sig, good)
            else "payload_changed")
