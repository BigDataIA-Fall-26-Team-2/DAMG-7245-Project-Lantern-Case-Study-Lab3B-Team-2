"""Replay / live modes: the default, live without a key, threads never mixing modes,
and the key never leaving the process.

There is no Gemini key in tests. Where a live graph is needed, the kit's stand-in
model plays Gemini, so nothing is called and nothing is written to outputs/cache.
"""
import contextlib

import pytest

import api.service as svc
from api.service import PanelService

ANTARES = "How many current holdings per investment type at Antares Strategic Credit Fund?"
ANTARES_SQL = ("SELECT investment_type, COUNT(*) AS n FROM holdings_v "
               "WHERE bdc = 'ANTARES STRATEGIC CREDIT FUND' GROUP BY investment_type ORDER BY investment_type")


@contextlib.contextmanager
def serving(client, service):
    """Swap the app's service for `service` while the block runs."""
    old = client.app.state.panel
    client.app.state.panel = service
    try:
        yield
    finally:
        client.app.state.panel = old
        service.close()


def live_service(live_model):
    """Replay from the real cache, live from a stand-in."""
    return PanelService(live_model=live_model)


# ------------------------------------------------------------------ default
def test_default_mode_is_replay(client, recorded):
    a = client.post("/ask", json={"question": recorded["q06"]["question"]}).json()
    assert a["mode"] == "replay" and a["row_count"] == 10 and a["fresh_model_calls"] == 0
    assert client.get(f"/conversations/{a['thread_id']}").json()["mode"] == "replay"
    c = client.post("/conversations").json()                       # no body: replay
    assert c["mode"] == "replay"


def test_mode_must_be_replay_or_live(client, recorded):
    r = client.post("/ask", json={"question": recorded["q06"]["question"], "mode": "record"})
    assert r.status_code == 422


# ------------------------------------------------------------------ live without a key
def test_live_without_a_key_is_400(client, recorded):
    r = client.post("/ask", json={"question": recorded["q06"]["question"], "mode": "live"})
    assert r.status_code == 400
    d = r.json()["detail"]
    assert d["code"] == "live_unavailable" and "GEMINI_API_KEY" in d["message"]


def test_live_conversation_without_a_key_is_400(client):
    r = client.post("/conversations", json={"mode": "live"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "live_unavailable"


def test_health_reports_live_unavailable(client):
    live = client.get("/health").json()["modes"]["live"]
    assert live["available"] is False and "restart the API" in live["reason"]


# ------------------------------------------------------------------ never mix modes
def test_switching_mode_starts_a_new_thread(client, recorded):
    from askpanel import standin
    with serving(client, live_service(standin.FixtureSQLModel(answers={ANTARES: [ANTARES_SQL]}))):
        assert client.get("/health").json()["modes"]["live"] == {"available": True, "reason": None}

        r1 = client.post("/ask", json={"question": recorded["q02"]["question"]}).json()
        a = r1["thread_id"]
        assert r1["mode"] == "replay" and r1["row_count"] == 15

        r2 = client.post("/ask", json={"question": ANTARES, "thread_id": a, "mode": "live"}).json()
        b = r2["thread_id"]
        assert b != a and r2["mode"] == "live" and r2["turn"] == 1
        assert r2["thread_reset"] is True and r2["previous_thread_id"] == a
        assert r2["rows"] == [["DEBT", 1326], ["EQUITY", 92], ["UNKNOWN", 70]]
        assert r2["fresh_model_calls"] == 1                     # the stand-in "called Gemini"

        # each thread kept its own mode and its own history
        ha, hb = (client.get(f"/conversations/{t}").json() for t in (a, b))
        assert (ha["mode"], len(ha["turns"])) == ("replay", 1)
        assert (hb["mode"], len(hb["turns"])) == ("live", 1)

        # back to replay on the live thread: new thread again
        r3 = client.post("/ask", json={"question": recorded["q06"]["question"], "thread_id": b}).json()
        assert r3["thread_id"] not in (a, b) and r3["thread_reset"] and r3["mode"] == "replay"

        # the original replay thread is untouched: its follow-up still replays
        r4 = client.post("/ask", json={"question": recorded["q03"]["question"], "thread_id": a}).json()
        assert r4["thread_id"] == a and r4["turn"] == 2 and r4["rows"] == [[106150000.0]]
        assert r4["thread_reset"] is False


def test_same_mode_keeps_the_thread(client, recorded):
    from askpanel import standin
    q2 = "How many current holdings does Antares Strategic Credit Fund report in total?"
    model = standin.FixtureSQLModel(answers={
        ANTARES: [ANTARES_SQL],
        q2: ["SELECT COUNT(*) AS n FROM holdings_v WHERE bdc = 'ANTARES STRATEGIC CREDIT FUND'"]})
    with serving(client, live_service(model)):
        t = client.post("/conversations", json={"mode": "live"}).json()
        assert t["mode"] == "live"
        r1 = client.post("/ask", json={"question": ANTARES, "thread_id": t["thread_id"], "mode": "live"}).json()
        r2 = client.post("/ask", json={"question": q2, "thread_id": t["thread_id"], "mode": "live"}).json()
        assert r1["thread_id"] == r2["thread_id"] == t["thread_id"] and r2["turn"] == 2
        assert r2["rows"] == [[1488]] and not r2["thread_reset"]


# ------------------------------------------------------------------ the key stays secret
FAKE_KEY = "AIzaFAKE_test_key_0123456789abcdefXYZ"


def test_key_is_never_returned(client, monkeypatch):
    monkeypatch.setattr(svc, "load_key", lambda: FAKE_KEY)

    def failing_gemini(req):
        raise RuntimeError(f"401 API key not valid: key={FAKE_KEY}")

    with serving(client, live_service(failing_gemini)):
        h = client.get("/health")
        assert FAKE_KEY not in h.text
        r = client.post("/ask", json={"question": ANTARES, "mode": "live"})
        assert r.status_code == 502 and r.json()["detail"]["code"] == "live_error"
        assert FAKE_KEY not in r.text and "[redacted]" in r.text
        assert FAKE_KEY not in client.get("/openapi.json").text


@pytest.mark.parametrize("text", [f"boom {FAKE_KEY}", "key AIzaSyA1234567890abcdefghijklmnop end"])
def test_scrub_removes_key_shaped_strings(monkeypatch, text):
    monkeypatch.setattr(svc, "load_key", lambda: FAKE_KEY)
    out = svc.scrub(text)
    assert "AIza" not in out and "[redacted]" in out
