"""The closed tool catalog (Case Study 3B, Appendix C)."""

CATALOG = {        # tool: (action class, scope kind)
    "list_mandates": ("READ", None),
    "bdc_holdings": ("READ", "public"),
    "bdc_signals": ("READ", "public"),
    "get_filing": ("READ", None),
    "mandate_profile": ("READ", "mandate"),
    "watchlist_read": ("READ", "mandate"),
    "memory_read": ("READ", "mandate"),
    "memory_propose_write": ("INTERNAL_WRITE", "mandate"),
    "watchlist_write": ("INTERNAL_WRITE", "mandate"),
    "draft_email": ("DRAFT", "mandate"),
    "request_approval": ("CONTROL", None),
    "send_email": ("EXTERNAL_SEND", "mandate"),
}

POLICY = {"READ": "auto", "DRAFT": "auto",
          "INTERNAL_WRITE": "notify", "EXTERNAL_SEND": "approve",
          "CONTROL": "principal", "DESTRUCTIVE": "forbidden"}
OVERRIDES = {"watchlist_write": "approve"}  # clients rely on it


def policy_for(tool):
    return OVERRIDES.get(tool, POLICY[CATALOG[tool][0]])


def conformance(registry):
    """registry: tool -> action class, as your server declares.
    Returns problems; [] means the catalog matches exactly."""
    out = [f"missing tool: {t}"
           for t in sorted(set(CATALOG) - set(registry))]
    out += [f"extra tool (the catalog is closed): {t}"
            for t in sorted(set(registry) - set(CATALOG))]
    out += [f"{t}: class {registry[t]}, expected {CATALOG[t][0]}"
            for t in sorted(set(CATALOG) & set(registry))
            if registry[t] != CATALOG[t][0]]
    return out
