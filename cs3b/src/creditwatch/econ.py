"""Unit economics, read from traces."""


def step_usd(t_in, t_out, p_in, p_out):
    """p_in, p_out: dollars per million tokens."""
    return (t_in * p_in + t_out * p_out) / 1e6


def trace_cost(trace):
    return sum(r.get("usd", 0.0) for r in trace)


def hours_saved_table(hours, rate, tasks):
    """The x0.5 / x1 / x2 sensitivity on time saved."""
    return [{"scenario": f"x{k:g}", "hours": hours * k * tasks,
             "usd": hours * k * tasks * rate}
            for k in (0.5, 1.0, 2.0)]
