"""Lab 4B self-check. Run from your cs4b/ folder:

    PYTHONPATH=src python -m askpanel.check

It checks that each Part exists and has the required shape. It does not
grade your answers: your demo video does that. On the bare kit most checks FAIL; read the list
as your to-do list.
"""
import ast
import json
import sys
import tempfile
from pathlib import Path

import yaml

from . import catalog, db, econ, questions

REQUIRED = ["sql/holdings_v.sql", "agent/contract.py", "services/mcp/server.py",
            "tests/test_server.py", "agent/mcp_client.py", "agent/model.py",
            "agent/graph.py", "agent/run.py", "app/streamlit_app.py",
            "questions/questions.yaml", "outputs/economics.md",
            "outputs/failures.md", "README.md"]
CONTRACT = {"SchemaCatalog", "QueryRequest", "SQLQuery", "QueryResult", "validate_query"}
GRAPH_NODES = {"load_schema", "generate", "check", "execute", "summarize"}
NO_DB = {"sqlite3", "duckdb", "sqlalchemy", "apsw"}


def _guard(fn):
    try:
        return fn()
    except FileNotFoundError as e:
        return False, f"missing {Path(e.filename).name if e.filename else e}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def _tree(path):
    return ast.parse(Path(path).read_text(encoding="utf-8"))


def registry_from(path):
    """REGISTRY = {"tool": "CLASS", ...} as a literal in your server."""
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "REGISTRY" for t in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError("no REGISTRY = {...} literal in services/mcp/server.py")


def direct_db_access(paths):
    """Imports or file paths that would let agent/ or app/ skip the server."""
    out = []
    for p in paths:
        for n in ast.walk(_tree(p)):
            if isinstance(n, ast.Import):
                out += [f"{p.name}: import {a.name}" for a in n.names
                        if a.name.split(".")[0] in NO_DB]
            elif isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] in NO_DB:
                out.append(f"{p.name}: from {n.module} import ...")
            elif isinstance(n, ast.Attribute) and n.attr in {"read_sql", "read_sql_query",
                                                              "connect_ro"}:
                out.append(f"{p.name}: .{n.attr}")
            elif (isinstance(n, ast.Constant) and isinstance(n.value, str)
                  and n.value.endswith((".sqlite", ".db"))):
                out.append(f"{p.name}: path {n.value!r}")
    return out


def contract_names(path):
    """Top-level classes and functions defined in agent/contract.py."""
    return {n.name for n in _tree(path).body
            if isinstance(n, (ast.ClassDef, ast.FunctionDef))}


def failure_entries(text):
    """'## ' sections whose 'What fixed it:' line is filled in (not blank,
    not the template's '(...)' placeholder)."""
    n = 0
    for block in ("\n" + text).split("\n## ")[1:]:
        for line in block.splitlines():
            if line.startswith("What fixed it:"):
                rest = line[len("What fixed it:"):].strip()
                n += bool(rest) and not rest.startswith("(")
                break
    return n


def graph_shape(path):
    names, cond, ckpt = set(), 0, False
    for n in ast.walk(_tree(path)):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if (n.func.attr == "add_node" and n.args
                    and isinstance(n.args[0], ast.Constant)):
                names.add(n.args[0].value)
            cond += n.func.attr == "add_conditional_edges"
            ckpt |= n.func.attr == "compile" and any(
                k.arg == "checkpointer" for k in n.keywords)
    out = [f"missing node: {x}" for x in sorted(GRAPH_NODES - names)]
    if cond < 2:
        out.append(f"{cond} conditional edge(s); check and execute each need one")
    if not ckpt:
        out.append("compile(...) has no checkpointer: follow-ups will not work")
    return out


def run_checks(root=None):
    root = Path(root or Path.cwd()).resolve()
    P = yaml.safe_load((root / "params.yaml").read_text())
    res = []

    def add(name, fn):
        ok, msg = _guard(fn)
        res.append((name, ok, msg))

    def layout():
        miss = [r for r in REQUIRED if not (root / r).exists()]
        return not miss, "all present" if not miss else f"missing: {miss}"

    def view_on(panel_path):
        sql = (root / "sql/holdings_v.sql").read_text()
        p = db.load_panel(root / panel_path)
        with tempfile.TemporaryDirectory() as d:
            probs = db.check_view(db.build_db(p, Path(d) / "t.sqlite", sql), p)
        return not probs, "meets the contract" if not probs else "; ".join(probs)

    def view_real():
        rp = P["data"].get("real_panel")
        if not rp or not (root / rp).exists():
            return False, (f"no real panel at {rp}: copy your Lab 3B panel there "
                           "(Parquet or CSV) or set data.real_panel")
        return view_on(rp)

    def contract():
        miss = sorted(CONTRACT - contract_names(root / "agent/contract.py"))
        return not miss, ("four models and validate_query defined" if not miss
                          else f"agent/contract.py does not define: {miss}")

    def cat():
        probs = catalog.conformance(registry_from(root / "services/mcp/server.py"))
        return not probs, "exactly the four READ tools" if not probs else "; ".join(probs)

    def readonly():
        src = (root / "services/mcp/server.py").read_text()
        if "set_authorizer(None" in src:
            return False, "the server removes the authorizer"
        if "connect_ro" not in src and "mode=ro" not in src:
            return False, "open the database with gate.connect_ro (mode=ro + authorizer)"
        t = (root / "tests/test_server.py").read_text()
        need = [w for w in ("INSERT", "DROP", "ATTACH", "PRAGMA", "sqlite_master", ";")
                if w not in t]
        return not need, ("refusal tests present" if not need
                          else f"tests/test_server.py never tries: {need}")

    def no_db():
        files = [p for d in ("agent", "app") for p in (root / d).rglob("*.py")
                 if p.name != "__init__.py"]
        if not files:
            return False, "no code in agent/ or app/ yet"
        probs = direct_db_access(files)
        return not probs, ("agent and app reach data only through the server"
                           if not probs else "; ".join(probs[:4]))

    def graph():
        probs = graph_shape(root / "agent/graph.py")
        return not probs, "nodes, conditional edges and checkpointer" if not probs else "; ".join(probs)

    def qs():
        probs = questions.validate(questions.load(root / "questions/questions.yaml"))
        return not probs, "ten questions, coverage met" if not probs else "; ".join(probs)

    def outputs():
        qs_ = questions.load(root / "questions/questions.yaml")
        cache = root / P["model"]["cache_dir"]
        probs = [] if P["data"].get("use_real") else [
            "data.use_real is false: record your ten questions on your real panel"]
        for q in qs_:
            f = root / "outputs/questions" / f"{q['id']}.json"
            if not f.exists():
                probs.append(f"{q['id']}: no output"); continue
            o = json.loads(f.read_text())
            probs += [f"{q['id']}: no {k}" for k in questions.OUTPUT_FIELDS if k not in o]
            if q.get("category") == "decline":
                if o.get("sql") is not None:
                    probs.append(f"{q['id']}: a decline question produced SQL")
            elif not o.get("sql") or not isinstance(o.get("result"), dict):
                probs.append(f"{q['id']}: no SQL or no result")
            keys = [t["request_key"] for t in o.get("trace", []) if t.get("node") == "generate"]
            if not keys:
                probs.append(f"{q['id']}: no model call in the trace")
            probs += [f"{q['id']}: request {k[:8]} not in the replay cache"
                      for k in keys if not (cache / f"{k}.json").exists()]
        return not probs, "all ten saved and replayable" if not probs else "; ".join(probs[:5])

    def economics():
        t = (root / "outputs/economics.md").read_text()
        lines = {l.split("|")[1].strip(): l for l in t.splitlines() if l.count("|") >= 3}
        miss = [k for k in econ.FIVE_LINES
                if k not in lines or not any(ch.isdigit() for ch in lines[k])]
        return not miss, "five lines, with numbers" if not miss else f"missing or no number: {miss}"

    def failures():
        t = (root / "outputs/failures.md").read_text()
        n = failure_entries(t)
        return n >= 3, f"{n} failure(s) with a filled-in fix (3 required)"

    add("All     required files present", layout)
    add("Part 0  holdings_v on the fixture", lambda: view_on(P["data"]["panel"]))
    add("Part 0  holdings_v on your real panel", view_real)
    add("Part 1  contract models", contract)
    add("Part 2  catalog conformance", cat)
    add("Part 2  read-only server and refusal tests", readonly)
    add("Part 3  no direct database access", no_db)
    add("Part 3  graph shape", graph)
    add("Part 5  question coverage", qs)
    add("Part 5  saved outputs and replay cache", outputs)
    add("Part 6  unit economics", economics)
    add("Part 6  failure log", failures)
    return res


def main():
    res = run_checks()
    for name, ok, msg in res:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:42s} {msg}")
    print(f"{sum(ok for _, ok, _ in res)}/{len(res)} checks pass")
    return 0 if all(ok for _, ok, _ in res) else 1


if __name__ == "__main__":
    sys.exit(main())
