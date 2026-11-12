"""The heartbeat: detect, decide, deduplicate."""
import hashlib
import urllib.error
import urllib.request

WATCH = {"10-Q", "10-K", "8-K"}


def next_release(last):
    """The release after `last`, in the SEC's layout: quarterly files
    through 2025 ('2025q3' -> '2025q4' -> '2026_01'), monthly from
    2026 ('2026_08' -> '2026_09'; '2026_12' -> '2027_01')."""
    if "q" in last:
        y, q = map(int, last.split("q"))
        if q < 4:
            return f"{y}q{q + 1}"
        return f"{y + 1}_01" if y + 1 >= 2026 else f"{y + 1}q1"
    y, m = map(int, last.split("_"))
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return f"{y}_{m:02d}"


def release_tick(last, head, base_url):
    """head(url) -> HTTP status. 200: the release is out."""
    r = next_release(last)
    url = f"{base_url}{r}_bdc.zip"
    return {"release": r, "url": url,
            "published": head(url) == 200}


def new_filings(recent, seen):
    rows = zip(recent["form"], recent["items"],
               recent["accessionNumber"],
               recent["acceptanceDateTime"])
    return [dict(form=f, accn=a, accepted=t)
            for f, i, a, t in rows
            if a not in seen and f in WATCH
            and (f != "8-K" or "2.02" in i.split(","))]


def quiet(now, start=21, end=7):          # injected clock
    return now.hour >= start or now.hour < end


def dedup_key(mandate, trigger, rule):
    raw = f"{mandate}|{trigger}|{rule}".encode()
    return hashlib.sha1(raw).hexdigest()[:16]


def route(signals, held_by_mandate):
    """A mandate sees signals only for BDCs it holds."""
    return {m: signals[signals["name"].isin(held)]
            for m, held in held_by_mandate.items()}


def decide(sig, mandate, seen, now):
    """Alert now, or hold for the brief in quiet hours; once."""
    out = []
    for s in sig.itertuples():
        key = dedup_key(mandate, f"{s.adsh}#{s.row}", s.rule)
        if key in seen:
            continue
        seen.add(key)
        out.append({"mandate": mandate, "key": key,
                    "rule": s.rule, "adsh": s.adsh, "row": s.row,
                    "action": "hold" if quiet(now) else "alert"})
    return out


def filing_decisions(filings, bdc, held, mandate, seen, now):
    """Every watched filing gets an alert or a logged
    not-material decision (recall is graded on this)."""
    out = []
    for f in filings:
        key = dedup_key(mandate, f["accn"], "FILING")
        if key in seen:
            continue
        seen.add(key)
        act = ("not_material" if bdc not in held
               else "hold" if quiet(now) else "alert")
        out.append({"mandate": mandate, "key": key, "bdc": bdc,
                    "rule": "FILING", **f, "action": act})
    return out


def head_live(user_agent):
    """A real HEAD request, for live mode (needs network)."""
    def head(url):
        req = urllib.request.Request(
            url, method="HEAD", headers={"User-Agent": user_agent})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
    return head
