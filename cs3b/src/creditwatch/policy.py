"""Standing rules, enforced in the tool server, not the prompt."""
import re
import unicodedata

ZW = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"))


def words(s):
    """NFKC, zero-width removed, lower, one space between."""
    s = unicodedata.normalize("NFKC", s).translate(ZW).lower()
    return " " + re.sub(r"[^0-9a-z]+", " ", s).strip() + " "


def squash(s):
    return words(s).replace(" ", "")


def mentions(text, names):
    t = words(text)                 # whole words only
    return [n for n in names if words(n) in t]


def leaks(text, canaries):
    t = squash(text)                # any spacing or zero-width
    return [c for c in canaries if squash(c) in t]


def policy_check(draft, mandate, registry, others):
    """First rule that fires, or None. others: the OTHER
    mandates' names, aliases and confidential terms."""
    allowed = {a.lower() for a in mandate["contacts"]} | {
        a.lower() for a in registry["bdc_ir"].values()}
    for r in draft["to"]:
        dom = r.split("@")[-1].lower()
        if dom in registry["borrower_domains"]:
            return "R-BORROWER"
        if r.lower() not in allowed:
            return "R-NOT-CONTACT"
    text = " ".join([draft["subject"], draft["body"],
                     *draft.get("attachments", [])])
    if mentions(text, others["names"]) or leaks(
            text, others["terms"]):
        return "R-OTHER-MANDATE"
    if mentions(text, registry["restricted"]):
        return "R-RESTRICTED"
    return None


def confidential_terms(mandates, active):
    """Every OTHER mandate's client name, aliases and registered
    confidential terms (account codes, mandate codes)."""
    names, terms = [], []
    for mid, m in mandates.items():
        if mid != active:
            names += [m["client"], *m.get("aliases", [])]
            terms += m.get("confidential_terms", [])
    return {"names": names, "terms": terms}
