"""The agent loop, with a budget guard and a trace."""
import hashlib
import json

from .catalog import CATALOG


def h12(x):
    raw = json.dumps(x, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:12]


def run_agent(model, tools, task, clock, max_steps=8,
              usd_cap=0.50, token_cap=60_000, run_id="run-1"):
    msgs = [{"role": "user", "content": task}]
    trace, spent, toks = [], 0.0, 0
    for step in range(1, max_steps + 1):
        out = model(msgs)              # via the replay client
        spent += out["usd"]
        toks += out["tokens_in"] + out["tokens_out"]
        rec = {"run_id": run_id, "step": step,
               "ts": clock().isoformat(),
               "rationale": out.get("rationale", ""),
               "tool": out.get("tool"), "usd": out["usd"],
               "tokens_in": out["tokens_in"],
               "tokens_out": out["tokens_out"]}
        if spent > usd_cap or toks > token_cap:
            why = ("budget_usd" if spent > usd_cap
                   else "budget_tokens")
            trace.append({**rec, "stop": why})
            return None, trace
        if out.get("tool") is None:      # final answer
            trace.append(rec)
            return out["text"], trace
        name = out["tool"]
        rec["action_class"] = CATALOG.get(name, ("UNKNOWN",))[0]
        rec["args_hash"] = h12(out["args"])
        try:
            obs = tools[name](**out["args"])
        except Exception as e:      # refusals are observations
            obs = {"error": type(e).__name__, "detail": str(e)}
        rec["observation_ref"] = h12(obs)
        trace.append(rec)
        msgs.append({"role": "tool", "name": name,
                     "content": json.dumps(obs, default=str)})
    trace.append({"run_id": run_id, "step": max_steps,
                  "ts": clock().isoformat(),
                  "stop": "max_steps"})
    return None, trace
