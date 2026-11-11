"""Measure working skills and verify pins. --lock explicitly approves current hashes."""
import argparse
import json
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from creditwatch import skills, workspace

REQUIRED = {"bdc-quarter-review", "client-monthly-note", "watchlist-entry", "release-brief", "ir-question", "signal-explainer"}


def measure(root=ROOT):
    root = Path(root)
    params = yaml.safe_load((root / "params.yaml").read_text())
    folder = root / params["agent"]["workspace"] / "skills"
    loaded = skills.load_skills(folder)
    missing = REQUIRED - loaded.keys()
    if missing: raise ValueError(f"Missing skills: {sorted(missing)}")
    for name, text in loaded.items():
        meta = skills.frontmatter(text)
        if meta.get("name") != name or not meta.get("description"):
            raise ValueError(f"Invalid frontmatter: {name}")
    scripted = [n for n in loaded if any((folder/n/"scripts").glob("*.py"))]
    if len(scripted) < 2: raise ValueError("Need at least two skills with scripts")
    count = lambda text: sum(workspace.ntok(line) for line in text.splitlines())
    index = skills.skill_index(loaded)
    full, compact = sum(count(t) for t in loaded.values()), count(index)
    budget = params["context"]["budgets"]["skills_index"]
    if compact > budget: raise ValueError("Skill index exceeds the context budget")
    report = {"method": "Notebook estimate: sum(max(1, len(line)//4)); not a model tokenizer",
              "skill_count": len(loaded), "scripted_skills": sorted(scripted),
              "full_skill_tokens": full, "index_tokens": compact,
              "tokens_saved": full-compact, "saving_percent": round(100*(1-compact/full), 2),
              "skills_index_budget": budget, "index_fits_budget": compact <= budget,
              "per_skill_tokens": {n: count(t) for n,t in loaded.items()},
              "folder_hashes": skills.lock(folder)}
    return folder, index, report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", action="store_true", help="Replace the lockfile after reviewing skill edits")
    parser.add_argument("--report", action="store_true", help="Save measurements and skill index in reports/skills/")
    args=parser.parse_args()
    folder,index,report=measure()
    pin=folder/"skills.lock"
    if args.lock:
        pin.write_text(json.dumps(report["folder_hashes"], indent=2, sort_keys=True)+"\n")
    skills.verify(folder,json.loads(pin.read_text()))
    if args.report:
        output=ROOT/"reports/skills";output.mkdir(parents=True,exist_ok=True)
        (output/"token_savings.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
        (output/"index.txt").write_text(index+"\n")
    print(f"{report['skill_count']} skills; {len(report['scripted_skills'])} with scripts; lockfile verified")
    print(f"Full instructions: {report['full_skill_tokens']} estimated tokens; index: {report['index_tokens']}")
    print(f"Saved: {report['tokens_saved']} tokens ({report['saving_percent']}%); budget: {report['skills_index_budget']}")


if __name__ == "__main__":main()
