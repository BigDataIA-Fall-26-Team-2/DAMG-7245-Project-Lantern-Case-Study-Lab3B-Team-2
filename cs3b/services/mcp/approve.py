"""Human-only approval console, never registered as an agent tool."""
import argparse
from getpass import getpass
import json
import re
from services.mcp.server import ROOT, authenticated_runtime
from creditwatch import approvals
from services.mcp.runtime import read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_id")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--mandate", default="mandate_a")
    args = parser.parse_args()
    if not re.fullmatch(r"req-[a-f0-9]{32}", args.request_id):
        parser.error("Invalid request id")
    runtime = authenticated_runtime(args.root, args.mandate, getpass("Priya session token: "))
    request = read(runtime.file("requests", args.request_id))
    if request is None:
        parser.error("Request not found in this mandate")
    envelope = request["envelope"]
    digest = approvals.payload_hash(envelope)
    print(json.dumps(envelope, indent=2))
    print("Payload hash:", digest)
    confirmation = input("To approve this exact payload, paste its full hash (anything else cancels): ").strip()
    if confirmation != digest:
        print("Cancelled. No approval issued.")
        return
    print("Approval token:", runtime.grant(args.request_id, confirmation))


if __name__ == "__main__":
    main()
