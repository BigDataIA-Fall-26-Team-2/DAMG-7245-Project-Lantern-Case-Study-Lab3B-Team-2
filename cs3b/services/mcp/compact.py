"""Review/apply a mandate's memory compaction; no model or API call."""
import argparse
from getpass import getpass
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
import yaml
from creditwatch import audit, channel
from services.mcp.server import create_runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mandate", required=True)
    parser.add_argument("--before", required=True, help="Exclusive cutoff YYYY-MM-DD")
    parser.add_argument("--apply", metavar="REVIEW_HASH", help="Apply the exact previously reviewed diff")
    args = parser.parse_args()
    params = yaml.safe_load((ROOT / "params.yaml").read_text())
    fx = ROOT / params["data"]["fixture_dir"]
    session = channel.login(params["agent"]["principal"], getpass("Priya session token: "),
                            args.mandate, json.loads((fx / "users.json").read_text()))
    audit_dir = ROOT / params["agent"]["workspace"] / "mandates" / session.mandate / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    runtime = create_runtime(session=session, ledger=audit.Ledger(path=audit_dir / "memory.jsonl"),
        mandates=json.loads((ROOT / params["data"]["mandates"]).read_text()))
    result = runtime.compact_memory(session.mandate, args.before, args.apply)
    print(result["diff"] or "No changes.")
    print("Review hash:", result["review_hash"])
    print("Applied; original logs retained." if args.apply else "Preview only; memory and logs unchanged.")


if __name__ == "__main__":
    main()
