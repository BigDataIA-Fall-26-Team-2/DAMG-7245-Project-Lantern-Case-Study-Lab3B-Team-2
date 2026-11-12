"""Signals JSON list -> deterministic, cited Markdown. No model or network calls."""
import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
import json


def cell(value):
    return str(value).replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def number(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("Expected a finite number")
    try:
        n = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Expected a finite number") from None
    if not n.is_finite():
        raise ValueError("Expected a finite number")
    return n


def explain(signal):
    required = ("name", "identifier", "rule", "adsh", "row", "prior_row", "before", "after")
    if not isinstance(signal, dict) or any(k not in signal or signal[k] is None or str(signal[k]).strip() == "" for k in required):
        raise ValueError("Signal is missing values or evidence references")
    before, after, rule = signal["before"], signal["after"], signal["rule"]
    if rule == "MARKDOWN":
        b, a = number(before), number(after)
        if a >= b: raise ValueError("MARKDOWN requires after < before")
        text = f"Value fell from {b:.2f} to {a:.2f}: down {b-a:.2f} points."
    elif rule == "PIK_UP":
        b, a = number(before), number(after)
        if b < 0 or a <= b: raise ValueError("PIK_UP requires nonnegative before and after > before")
        text = f"PIK rate rose from {b:.2f}% to {a:.2f}%: up {a-b:.2f} percentage points."
    elif rule == "EXTENDED":
        b, a = date.fromisoformat(str(before)), date.fromisoformat(str(after))
        if a <= b: raise ValueError("EXTENDED requires a later maturity")
        text = f"Maturity moved from {b.isoformat()} to {a.isoformat()}: {(a-b).days} days later."
    else:
        raise ValueError("Unsupported signal rule")
    cite = f"{signal['adsh']}; current row {signal['row']}; prior row {signal['prior_row']}"
    return [signal["name"], signal["identifier"], text, cite]


def render(signals):
    if not isinstance(signals, list): raise ValueError("Input must be a JSON list")
    rows = [explain(s) for s in signals]
    lines = ["| BDC | Holding | Observed change | Evidence |", "|---|---|---|---|"]
    for row in sorted(rows, key=lambda r: tuple(str(v) for v in r)):
        lines.append("| " + " | ".join(cell(v) for v in row) + " |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("signals")
    args = parser.parse_args()
    try:
        with open(args.signals, encoding="utf-8") as f:
            text = render(json.load(f))
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    print(text)


if __name__ == "__main__":
    main()
