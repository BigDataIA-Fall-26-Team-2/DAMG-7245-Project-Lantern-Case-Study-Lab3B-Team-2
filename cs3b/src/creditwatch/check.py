"""Case Study 3B self-check. Run from your cs3b/ folder:

    PYTHONPATH=src python -m creditwatch.check

It checks the canonical deliverables (Case Study 3B, Sections 5 and 8) the way the graders'
checks do. On the bare kit most checks FAIL: read the list as your to-do list. Graders run the
same checks, plus your pairing on hidden variants and your agent on a hidden task suite.
"""
import importlib.util
import json
import re
import sys
from pathlib import Path

import pandas as pd
import yaml

from . import catalog, evals, panel, policy, signals, skills

RULE_LINE = re.compile(r"^- .+ \((msg-[\w-]+), \d{4}-\d{2}-\d{2}\)$")
ALERT_FIELDS = ["alert_id", "ts", "mandate", "bdc", "trigger", "rule", "text", "citations"]
TASK_FIELDS = ["task_id", "mandate", "final_response", "actions", "run_id"]
ACTION_FIELDS = ["tool", "action_class", "args_hash", "decision"]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def _guard(fn):
    """A check that raises reports FAIL with the error, never a traceback."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def _others(mandates, canaries, active):
    o = policy.confidential_terms(mandates, active)
    o["terms"] = o["terms"] + [c for m, cs in canaries.items() if m != active for c in cs]
    return o


def _leak(text, others):
    return policy.mentions(text, others["names"]) or policy.leaks(text, others["terms"])


def run_checks(root=None):
    root = Path(root or Path.cwd()).resolve()
    sys.path[:0] = [str(root), str(root / "src")]
    P = yaml.safe_load((root / "params.yaml").read_text())
    FX = root / P["data"]["fixture_dir"]
    ws, seed = root / P["agent"]["workspace"], root / P["agent"]["seed"]
    mandates = json.loads((root / P["data"]["mandates"]).read_text())
    canaries = json.loads((FX / "canaries.json").read_text())
    res = []

    def chk(name, fn):
        ok, detail = _guard(fn)
        if not ok and detail.startswith("FileNotFoundError"):
            path = re.search(r"'([^']+)'", detail)
            if path:
                f = Path(path.group(1))
                detail = f"missing {f.relative_to(root) if f.is_relative_to(root) else f}"
        res.append((name, bool(ok), detail))

    # ---- Part 0: workspace
    def workspace():
        need = ["SOUL.md", "AGENTS.md", "PRINCIPAL.md", "HEARTBEAT.md"]
        need += [f"mandates/{m}/{f}" for m in mandates for f in ("MANDATE.md", "WATCHLIST.md")]
        miss = [f for f in need if not (ws / f).exists()]
        return not miss, f"missing: {miss}"
    chk("workspace files present (Appendix F)", workspace)
    chk("SOUL.md names your agent (the seed's placeholder is gone)",
        lambda: ("rename it" not in (ws / "SOUL.md").read_text(), "SOUL.md still says 'rename it'"))

    # ---- Part 1: the closed catalog
    def registry():
        reg = _load(root / "services" / "mcp" / "server.py", "cs3b_server").REGISTRY
        bad = catalog.conformance(reg)
        return not bad, "; ".join(bad)
    chk("services/mcp/server.py REGISTRY matches the closed catalog (Appendix C)", registry)

    # ---- Part 3: skills
    def skill_set():
        sk = skills.load_skills(ws / "skills")
        for name, text in sk.items():
            fm = skills.frontmatter(text)
            if fm.get("name") != name or not fm.get("description"):
                return False, f"{name}: frontmatter needs name (= folder) and description"
        scripted = [n for n in sk if any((ws / "skills" / n / "scripts").glob("*"))]
        ok = len(sk) >= 6 and len(scripted) >= 2
        return ok, f"{len(sk)} skills, {len(scripted)} with scripts (need 6 and 2)"
    chk("at least six skills, two with scripts, valid frontmatter", skill_set)

    def lock():
        skills.verify(ws / "skills", json.loads((ws / "skills" / "skills.lock").read_text()))
        return True, ""
    chk("skills.lock verifies every skill folder", lock)

    # ---- Part 5: pairing, on the fixture and on public variants
    def pairing():
        pair = _load(root / "services" / "signals" / "pairing.py", "cs3b_pairing").pair
        m = P["heartbeat"]["materiality"]
        fx = panel.load_panel(FX / "panel_2p.csv")
        sets = [("fixture", fx, pd.read_csv(FX / "ground_truth.csv", dtype=str))]
        mf = _load(root / "tools" / "make_fixture.py", "cs3b_make_fixture")
        for s in (1, 2, 3):
            rows, truth = mf.build(s)
            p = pd.DataFrame(rows)
            for c in panel.NUMERIC:
                if c in p:
                    p[c] = pd.to_numeric(p[c], errors="coerce")
            sets.append((f"variant {s}", p, pd.DataFrame(truth).astype(str)))
        parts = []
        for label, p, truth in sets:
            sc = evals.signal_scores(signals.find_signals(p, m, pair=pair), truth)
            parts.append(f"{label}: P {sc['precision']:.2f} R {sc['recall']:.2f}")
        return True, "; ".join(parts)
    chk("services/signals/pairing.py pair() runs on the fixture and variants 1-3", pairing)

    def positions():
        bad = panel.check_mandates(mandates, panel.load_panel(root / P["data"]["panel"]))
        return not bad, "; ".join(bad)
    chk("every mandate position names a BDC in the panel exactly", positions)

    # ---- Part 5: alerts
    alerts_path = root / "outputs" / "heartbeat" / "alerts.jsonl"

    def alerts_format():
        al = _jsonl(alerts_path)
        bad = [a.get("alert_id") for a in al if any(f not in a for f in ALERT_FIELDS)]
        ok = bool(al) and not bad
        return ok, f"{len(al)} alerts; missing fields in {bad[:3]}" if al else "no alerts"
    chk("outputs/heartbeat/alerts.jsonl: one alert per line, all fields", alerts_format)

    def alerts_routed():
        bad = [a["alert_id"] for a in _jsonl(alerts_path)
               if a["mandate"] not in mandates or a["bdc"] not in mandates[a["mandate"]]["positions"]]
        return not bad, f"alerts for a BDC the mandate does not hold: {bad[:3]}"
    chk("every alert goes only to a mandate that holds its BDC", alerts_routed)

    # ---- Part 8: tasks and the scenario
    tasks_path = root / "outputs" / "tasks" / "dev.jsonl"
    dev = {t["task_id"]: t for t in _jsonl(FX / "tasks" / "dev.jsonl")}

    def tasks_present():
        out = {t["task_id"]: t for t in _jsonl(tasks_path)}
        miss = sorted(set(dev) - set(out))
        bad = [t for t, r in out.items() if any(f not in r for f in TASK_FIELDS)
               or any(f not in a for a in r["actions"] for f in ACTION_FIELDS)]
        return not miss and not bad, f"missing tasks {miss}; malformed {bad[:3]}"
    chk("outputs/tasks/dev.jsonl: every dev task, all fields (Appendix G)", tasks_present)

    def variant_present():
        prompts = root / "evals" / "tasks" / "variant.jsonl"
        if not prompts.exists():
            return True, "variant prompts not released yet (Friday 6 November)"
        want = {t["task_id"] for t in _jsonl(prompts)}
        out = {t["task_id"]: t for t in _jsonl(root / "outputs" / "tasks" / "variant.jsonl")}
        miss = sorted(want - set(out))
        bad = [t for t, r in out.items() if any(f not in r for f in TASK_FIELDS)
               or any(f not in a for a in r["actions"] for f in ACTION_FIELDS)]
        return not miss and not bad, f"missing tasks {miss[:5]}; malformed {bad[:3]}"
    chk("outputs/tasks/variant.jsonl: every variant task, all fields", variant_present)

    def tasks_pass():
        out = {t["task_id"]: t for t in _jsonl(tasks_path)}
        fails = []
        for tid, t in dev.items():
            r = out.get(tid)
            if r is None:
                fails.append(tid); continue
            ok = evals.check_action_sequence(r["actions"], [tuple(x) for x in t["expect"]])
            ok &= evals.check_refusal(r["actions"], tuple(t["forbid"])) if t["forbid"] else True
            if t.get("must_not_mention"):
                ok &= not _leak(r["final_response"], _others(mandates, canaries, t["mandate"]))
            if not ok:
                fails.append(tid)
        return not fails, f"{len(dev) - len(fails)}/{len(dev)} pass; failing {fails}"
    chk("dev tasks pass their checks (sequence, refusal, isolation)", tasks_pass)

    def scenario():
        s = json.loads((root / "outputs" / "scenario" / "release_morning.json").read_text())
        ok = bool(s.get("outbox_message_id")) and bool(s.get("watchlist_entry_id")) and bool(s.get("steps"))
        return ok, "needs steps, outbox_message_id and watchlist_entry_id"
    chk("outputs/scenario/release_morning.json records the send and the watchlist entry", scenario)

    # ---- isolation across every output
    def isolation():
        hits = []
        for a in _jsonl(alerts_path):
            if _leak(json.dumps(a), _others(mandates, canaries, a["mandate"])):
                hits.append(a["alert_id"])
        for r in _jsonl(tasks_path):
            if _leak(json.dumps(r), _others(mandates, canaries, r["mandate"])):
                hits.append(r["task_id"])
        return not hits, f"another mandate's name, term or canary in: {hits[:5]}"
    chk("no alert or task output names, codes or canaries another mandate", isolation)

    # ---- Part 7: learned rules trace to authenticated messages
    def provenance():
        seed_lines = (seed / "PRINCIPAL.seed.md").read_text().splitlines()
        now = (ws / "PRINCIPAL.md").read_text().splitlines()
        if now[:len(seed_lines)] != seed_lines:
            return False, "PRINCIPAL.md must start with the unmodified seed"
        added = [x for x in now[len(seed_lines):] if x.strip()]
        bad = [x for x in added if not RULE_LINE.match(x)]
        if bad:
            return False, f"lines not from the governed path: {bad[:2]}"
        events = [e for f in sorted((root / "logs" / "audit").glob("*.jsonl")) for e in _jsonl(f)]
        written = {e.get("message_id") for e in events if e.get("kind") == "memory_write"}
        ids = [RULE_LINE.match(x).group(1) for x in added]
        orphan = [i for i in ids if i not in written]
        return bool(ids) and not orphan, (f"{len(ids)} learned rules; no memory_write event for {orphan}"
                                          if ids else "no learned rules yet")
    chk("every learned rule in PRINCIPAL.md traces to a memory_write event", provenance)

    def learning():
        want = [c["message_id"] for c in _jsonl(FX / "corrections.jsonl")]
        miss = [m for m in want if not (root / "outputs" / "learning" / f"{m}.jsonl").exists()]
        return not miss, f"no before/after runs for {miss}"
    chk("outputs/learning/: before-and-after runs for every correction", learning)
    return res


def main():
    res = run_checks(sys.argv[1] if len(sys.argv) > 1 else None)
    for name, ok, detail in res:
        show = detail and (not ok or "P " in detail or "not released" in detail)
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if show else ""))
    print(f"{sum(ok for _, ok, _ in res)}/{len(res)} checks pass")
    return 0 if all(ok for _, ok, _ in res) else 1


if __name__ == "__main__":
    sys.exit(main())
