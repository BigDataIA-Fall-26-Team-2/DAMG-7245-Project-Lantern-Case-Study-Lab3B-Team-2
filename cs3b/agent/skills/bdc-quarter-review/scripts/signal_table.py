"""Deterministic signals JSON list -> Markdown table with both evidence rows."""
import json
import sys

COLS = ["BDC", "Holding", "Signal", "Before", "After", "Accession", "Row", "Prior row"]


def fmt(v):
    s = f"{v:.2f}" if isinstance(v, float) else str(v)
    return s.replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def short(name):
    return " ".join(w if w == "BDC" else w.title() for w in name.replace("FIXTURE ", "").split())


def table(signals):
    out = ["| " + " | ".join(COLS) + " |", "|" + "---|" * len(COLS)]
    for s in sorted(signals, key=lambda s: (s["name"], s["adsh"], s["rule"], str(s["row"]),
                                           str(s["prior_row"]), s["identifier"], json.dumps(s, sort_keys=True))):
        cells = [short(s["name"]), s["identifier"], s["rule"], s["before"], s["after"],
                 s["adsh"], s["row"], s["prior_row"]]
        out.append("| " + " | ".join(fmt(c) for c in cells) + " |")
    return "\n".join(out)


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        print(table(json.load(f)))
