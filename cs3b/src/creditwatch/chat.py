"""Part 0: authenticated, mandate-bound context inspection (no model yet)."""
import argparse
from dataclasses import dataclass
from getpass import getpass
import json
from pathlib import Path

import yaml

from . import channel, policy, skills, workspace


@dataclass(frozen=True)
class ChatSession:
    principal: str
    mandate: str
    context: str

    def reply(self, message):
        command = message.strip().lower()
        if command == "/context":
            return self.context
        if command == "/session":
            return f"Principal: {self.principal} | Active mandate: {self.mandate}"
        if command == "/help":
            return "/session: active client; /context: assembled context; /help: commands; /quit: exit CLI. Log out to change mandate."
        return (f"Active mandate: {self.mandate}. Your authenticated message was received. "
                "Part 0 has no model or action tools connected yet. Use /context, /session or /help.")


class Harness:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.params = yaml.safe_load((self.root / "params.yaml").read_text())
        fixture = self.root / self.params["data"]["fixture_dir"]
        self.users = json.loads((fixture / "users.json").read_text())

    def login(self, principal, token, mandate):
        session = channel.login(principal, token, mandate, self.users)
        ws = self.root / self.params["agent"]["workspace"]
        if not (ws / "mandates" / session.mandate / "MANDATE.md").is_file():
            raise ValueError("Workspace missing. Run notebook 00 first.")
        skills.verify(ws / "skills", json.loads((ws / "skills/skills.lock").read_text()))
        index = skills.skill_index(skills.load_skills(ws / "skills"))
        context, _ = workspace.assemble(
            workspace.load_parts(ws, session.mandate, skills_index=index),
            self.params["context"]["budgets"],
        )
        fixture = self.root / self.params["data"]["fixture_dir"]
        mandates = json.loads((self.root / self.params["data"]["mandates"]).read_text())
        canaries = json.loads((fixture / "canaries.json").read_text())
        forbidden = policy.confidential_terms(mandates, session.mandate)
        terms = forbidden["terms"] + [c for m, cs in canaries.items() if m != session.mandate for c in cs]
        if policy.mentions(context, forbidden["names"]) or policy.leaks(context, terms):
            raise PermissionError("Context contains another mandate's confidential information")
        return ChatSession(session.principal, session.mandate, context)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--mandate", default="mandate_a")
    args = parser.parse_args()
    try:
        session = Harness(args.root).login("priya", getpass("Priya session token: "), args.mandate)
    except (PermissionError, ValueError, FileNotFoundError, RuntimeError) as exc:
        parser.exit(1, f"Login failed: {exc}\n")
    print(session.reply("/session"))
    print(session.reply("/help"))
    while True:
        try:
            message = input("Priya> ")
        except (EOFError, KeyboardInterrupt):
            print("\nLogged out.")
            break
        if message.strip().lower() == "/quit":
            break
        print(session.reply(message))


if __name__ == "__main__":
    main()
