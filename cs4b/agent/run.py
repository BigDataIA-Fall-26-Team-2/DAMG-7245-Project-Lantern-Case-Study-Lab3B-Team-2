"""Answer questions/questions.yaml and save one JSON per question (Lab 35B/36B).

    python agent/run.py --mode replay          # default: from outputs/cache, no key
    python agent/run.py --mode record          # calls Gemini once per new request
    python agent/run.py --mode replay --verify # replay twice; fail unless byte-identical

Each question runs on its own thread; a follow_up runs on the thread of the
question it follows, so it sees that question and its SQL in its history.
Output: outputs/questions/<id>.json (id, question, category, sql, answer, result,
trace, usd, ...). The database is reached only through the MCP server.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent  # noqa: E402,F401  (paths)
from agent import ROOT  # noqa: E402
from agent.graph import ask, build_graph, model_calls  # noqa: E402
from agent.mcp_client import PanelClient  # noqa: E402
from agent.model import PARAMS, make_model  # noqa: E402
from askpanel import clock, llm, questions, standin  # noqa: E402


def record_of(q, s):
    query = s.get("query") or {}
    result = s.get("result")
    if result is not None:
        result = {k: v for k, v in result.items() if k != "ms"}   # wall time: not replayable
    return {"id": q["id"], "question": q["question"], "category": q["category"],
            "follows": q.get("follows"), "sql": query.get("sql"),
            "decline": query.get("decline"), "explanation": query.get("explanation"),
            "answer": s.get("answer"), "result": result, "error": s.get("error"),
            "stop": s.get("stop"), "attempts": s.get("attempt"),
            "model_calls": model_calls(s), "usd": round(s.get("usd", 0.0), 8),
            "tokens": s.get("tokens", 0), "history": s.get("history", []),
            "trace": s.get("trace", [])}


def dumps(o):
    return json.dumps(o, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def run_all(qs, mode, model_call=None, model_name=None, cache=None):
    """{id: saved record} for every question, in order. Raises CacheMiss in replay
    if a request was never recorded."""
    params = PARAMS if cache is None else {**PARAMS, "model": {**PARAMS["model"], "cache_dir": cache}}
    m = make_model(mode, params=params, call=model_call)
    out, threads = {}, {}
    with PanelClient() as c:
        app = build_graph(m, c.tools(), clock.clock, PARAMS, model_name=model_name)
        for q in qs:
            thread = threads.get(q.get("follows"), q["id"]) if q["category"] == "follow_up" else q["id"]
            threads[q["id"]] = thread
            s = ask(app, q["question"], thread_id=thread, run_id=q["id"])
            out[q["id"]] = record_of(q, s)
            r = out[q["id"]]
            print(f"  {q['id']:4s} {q['category']:11s} calls={r['model_calls']} "
                  f"usd={r['usd']:.6f} {'sql' if r['sql'] else 'no sql'}"
                  f"{' rows=' + str(r['result']['row_count']) if r['result'] else ''}"
                  f"  {(r['answer'] or '').splitlines()[0][:60]}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=["record", "replay"], default=PARAMS["model"]["mode"])
    ap.add_argument("--questions", default="questions/questions.yaml")
    ap.add_argument("--out", default="outputs/questions")
    ap.add_argument("--only", nargs="*", help="question ids (a follow_up also needs the one it follows)")
    ap.add_argument("--verify", action="store_true", help="run twice and compare bytes")
    ap.add_argument("--cache", help="replay cache directory (default: params model.cache_dir)")
    ap.add_argument("--standin", action="store_true",
                    help="offline development on the fixture: the kit's stand-in model, not Gemini")
    a = ap.parse_args(argv)

    qs = questions.load(ROOT / a.questions)
    probs = questions.validate(qs)
    if probs and a.questions == "questions/questions.yaml":
        print("questions.yaml:", "; ".join(probs))
    if a.only:
        qs = [q for q in qs if q["id"] in a.only]
    call, name = (standin.FixtureSQLModel(), "stand-in") if a.standin else (None, None)
    print(f"{len(qs)} question(s), mode={a.mode}, model={name or PARAMS['model']['name']}")
    try:
        runs = [run_all(qs, a.mode, call, name, a.cache)]
        if a.verify:
            runs.append(run_all(qs, "replay", None, name, a.cache))
    except llm.CacheMiss as e:
        sys.exit(f"CacheMiss {e}: this request was never recorded. Record it with "
                 "--mode record (needs GEMINI_API_KEY), or check that model.name, the "
                 "column descriptions and the question text match the recording.")
    out_dir = ROOT / a.out
    out_dir.mkdir(parents=True, exist_ok=True)
    for qid, rec in runs[0].items():
        with open(out_dir / f"{qid}.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(dumps(rec))
    usd = sum(r["usd"] for r in runs[0].values())
    print(f"wrote {len(runs[0])} file(s) to {a.out}; total usd {usd:.6f}")
    if a.verify:
        same = all(dumps(runs[0][k]) == dumps(runs[1][k]) for k in runs[0])
        print("two runs byte-identical:", same)
        if not same:
            sys.exit(1)


if __name__ == "__main__":
    main()
