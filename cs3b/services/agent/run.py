"""Record dev-01 with OpenAI; replay twice offline using frozen context and tool results."""
import argparse
from datetime import datetime
from getpass import getpass
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
import yaml
from creditwatch import clock, loop, skills, workspace
from creditwatch.llm import CacheMiss, request_key
from services.mcp.server import authenticated_runtime
from services.mcp.schemas import INPUTS
from services.agent.model import OpenAIProvider, RoutedModel

READ_TOOLS = ("mandate_profile", "bdc_signals", "bdc_holdings", "get_filing", "watchlist_read", "memory_read")

def dump(value):
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(value))


def execute(bundle, mode, provider=None, runtime=None):
    bundle = Path(bundle)
    manifest = json.loads((bundle / "manifest.json").read_text())
    observations_path = bundle / "tool_observations.json"
    observations = json.loads(observations_path.read_text()) if observations_path.exists() else {}
    model = RoutedModel(bundle / "responses", mode, manifest["models"], manifest["context"], manifest["tools"], provider)
    task, budget = manifest["task"], manifest["budget"]
    def tool(name, args):
        key = request_key({"tool": name, "args": args})
        if key not in observations:
            if mode != "record" or runtime is None:
                raise CacheMiss("Missing recorded tool observation")
            observations[key] = json.loads(dump(runtime.call(name, args)))
            save(observations_path, observations)
        return observations[key]
    assessment_trace = []
    for phase in ("triage", "materiality"):
        evidence = {"task": task["prompt"]}
        if phase == "materiality":
            evidence.update({"profile": tool("mandate_profile", {"scope": task["mandate"]}),
                             "signals": tool("bdc_signals", {"scope": "public"}),
                             "thresholds": manifest["materiality"]})
        answer = model.ask(phase, evidence)
        model.brief[phase] = answer["text"]
        assessment_trace.append({"phase": phase, **answer})
        if sum(e["usd"] for e in model.events) > budget["usd_cap_per_task"]:
            raise RuntimeError("Dollar budget exhausted during assessments")
        if sum(e["tokens_in"] + e["tokens_out"] for e in model.events) > budget["token_cap_per_task"]:
            raise RuntimeError("Token budget exhausted during assessments")
    spent = sum(e["usd"] for e in model.events)
    tokens = sum(e["tokens_in"] + e["tokens_out"] for e in model.events)
    functions = {name: (lambda name=name, **args: tool(name, args)) for name in READ_TOOLS}
    fixed = datetime.fromisoformat(manifest["clock"])
    text, trace = loop.run_agent(model, functions, task["prompt"], lambda: fixed,
        max_steps=budget["max_steps_per_task"], usd_cap=budget["usd_cap_per_task"] - spent,
        token_cap=budget["token_cap_per_task"] - tokens, run_id=task["task_id"])
    if text is None:
        raise RuntimeError("Agent stopped before completing: " + trace[-1].get("stop", "unknown"))
    if not all(any(row.get("tool") == name for row in trace) for name in ("mandate_profile", "bdc_signals")):
        raise RuntimeError("dev-01 did not call its required tools; recording is not accepted as complete")
    result = {"task_id": task["task_id"], "mandate": task["mandate"], "final_response": text,
              "assessments": assessment_trace, "trace": trace, "model_calls": model.events}
    return result


def verify(bundle):
    a = execute(bundle, "replay")
    b = execute(bundle, "replay")
    raw_a, raw_b = dump(a), dump(b)
    if raw_a != raw_b:
        raise RuntimeError("Replay traces differ")
    recorded = Path(bundle) / "recorded.json"
    if not recorded.exists() or recorded.read_text() != raw_a:
        raise RuntimeError("Replay differs from the completed recording")
    save(Path(bundle) / "replay-1.json", a)
    save(Path(bundle) / "replay-2.json", b)
    report = {"identical": True, "matches_recording": True, "provider_calls_during_replay": 0,
              "sha256": hashlib.sha256(raw_a.encode()).hexdigest(),
              "provenance": json.loads((Path(bundle) / "manifest.json").read_text())["provenance"]}
    save(Path(bundle) / "verification.json", report)
    return report


def prepare(root, bundle, runtime):
    root, bundle = Path(root), Path(bundle)
    if (bundle / "manifest.json").exists():
        return  # Keep the frozen inputs for recording resumption.
    settings = yaml.safe_load((root / "params.yaml").read_text())
    if not settings["data"]["use_fixture"]:
        raise ValueError("This demo records fictional fixture data only")
    models = yaml.safe_load((root / "services/agent/models.yaml").read_text())
    tasks = [json.loads(line) for line in (root / settings["data"]["fixture_dir"] / "tasks/dev.jsonl").read_text().splitlines() if line.strip()]
    task = next(t for t in tasks if t["task_id"] == "dev-01")
    ws = root / settings["agent"]["workspace"]
    index = skills.skill_index(skills.load_skills(ws / "skills"))
    context, _ = workspace.assemble(workspace.load_parts(ws, task["mandate"], skills_index=index), settings["context"]["budgets"])
    manifest = {"provenance": "openai-live", "task": task, "clock": clock.clock().isoformat(),
                "context": context, "models": models, "budget": settings["budget"],
                "materiality": settings["heartbeat"]["materiality"],
                "tools": {name: INPUTS[name].model_json_schema() for name in READ_TOOLS}}
    save(bundle / "manifest.json", manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["record", "verify"])
    parser.add_argument("--bundle", type=Path, default=ROOT / "evals/recordings/dev-01")
    args = parser.parse_args()
    if args.mode == "record":
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False, interpolate=False)
        key = os.environ.get("OPENAI_API_KEY") or getpass("OpenAI API key (hidden, not saved): ")
        token = os.environ.get("CREDITWATCH_SESSION_TOKEN") or getpass("Priya session token: ")
        runtime = authenticated_runtime(ROOT, "mandate_a", token)
        prepare(ROOT, args.bundle, runtime)
        provider = OpenAIProvider(key)
        result = execute(args.bundle, "record", provider, runtime)
        save(args.bundle / "recorded.json", result)
        print("Live provider calls this run:", provider.calls)
    print(dump(verify(args.bundle)))


if __name__ == "__main__":
    main()
