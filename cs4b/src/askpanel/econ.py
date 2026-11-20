"""Unit economics, read from your saved outputs and traces."""


def step_usd(t_in, t_out, p_in, p_out):
    """p_in, p_out: dollars per million tokens."""
    return (t_in * p_in + t_out * p_out) / 1e6


def summary(outputs):
    """outputs: the dicts saved in outputs/questions/. Feeds the five-line table."""
    n = len(outputs) or 1
    gens = [sum(t.get("node") == "generate" for t in o["trace"]) for o in outputs]
    return {"questions": len(outputs),
            "usd_total": round(sum(o.get("usd", 0.0) for o in outputs), 6),
            "usd_per_question": round(sum(o.get("usd", 0.0) for o in outputs) / n, 6),
            "model_calls_per_question": round(sum(gens) / n, 2),
            "repaired": sum(g > 1 for g in gens),
            "no_sql": sum(o.get("sql") is None for o in outputs)}   # declined or failed


def hours_saved_table(hours, rate, tasks):
    """The x0.5 / x1 / x2 sensitivity on time saved."""
    return [{"scenario": f"x{k:g}", "hours": hours * k * tasks,
             "usd": hours * k * tasks * rate} for k in (0.5, 1.0, 2.0)]


FIVE_LINES = ["Cost per completed task", "Latency", "Human time saved",
              "Quality", "Cost of failure"]
