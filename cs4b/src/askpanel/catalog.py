"""The closed tool catalog for the Lab 4B query server: four READ tools."""

CATALOG = {
    "list_tables": "READ",      # tables and views the agent may query
    "describe_table": "READ",   # columns, types, and a description of each
    "sample_values": "READ",    # distinct values of one column (names, types)
    "run_query": "READ",        # one gated, capped, timed SELECT
}


def conformance(registry):
    """registry: tool -> action class, as your server declares it.
    [] means the catalog matches exactly."""
    out = [f"missing tool: {t}" for t in sorted(set(CATALOG) - set(registry))]
    out += [f"extra tool (the catalog is closed): {t}"
            for t in sorted(set(registry) - set(CATALOG))]
    out += [f"{t}: class {registry[t]}, expected {CATALOG[t]}"
            for t in sorted(set(CATALOG) & set(registry)) if registry[t] != CATALOG[t]]
    return out
