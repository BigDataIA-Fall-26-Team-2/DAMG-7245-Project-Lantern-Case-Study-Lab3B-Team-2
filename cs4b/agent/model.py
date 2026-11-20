"""The SQL-writing model behind record/replay (Lab 35B).

    replay (default): reads outputs/cache/ only. No key, no network, no cost.
    record:           calls Gemini (model.name in params.yaml) with GEMINI_API_KEY,
                      read from the environment or from cs4b/.env (gitignored),
                      and stores each response under the SHA-256 of the full request.

Each stored response carries sql or decline, the explanation, token counts, the
dollar cost at params.yaml prices, and the measured latency of the call, so replay
reproduces cost and latency exactly.
"""
import json
import os
import re
import time

import yaml

from agent import ROOT
from askpanel import econ, llm

PARAMS = yaml.safe_load((ROOT / "params.yaml").read_text())

RULES = """Rules:
- SQLite dialect. Exactly ONE statement: SELECT or WITH ... SELECT. No semicolon.
- Use only the tables and columns listed. Prefer holdings_v (current-period holdings,
  one row per holding, BDC name in column bdc).
- holdings_v has only the CURRENT schedule. For anything about the prior schedule or a
  change over time, use holdings (period_role = 'current' or 'prior') joined to
  filings on adsh (BDC name in filings.name).
- Filter a BDC with bdc = '<exact name>' (or filings.name = '<exact name>'), copying
  the name from the exact values listed above. Never use LIKE for a BDC name: a
  pattern can also match a sibling fund (for example a '... II LLC').
- A "debt holding" is: investment_type = 'DEBT' OR (investment_type = 'UNKNOWN' AND
  is_debt = 1). UNKNOWN rows with a principal are loans the filing did not tag (for
  example "One stop" loans); EQUITY is never debt, even with a principal.
- To split the book into debt and equity, GROUP BY investment_type and report UNKNOWN
  separately instead of folding it into either side.
- For a change between the prior and the current schedule, aggregate once over
  holdings h JOIN filings f ON f.adsh = h.adsh with conditional sums, for example
  SUM(CASE WHEN h.period_role = 'prior' THEN h.fair_value END) AS prior_fair_value,
  and return prior, current and change (current - prior) as columns, one row per BDC.
  Every join must link on adsh: never ON 1=1 or CROSS JOIN.
- Money columns are in US dollars; rates are decimals (0.02 = 2%).
- Give columns readable aliases, ORDER BY something meaningful, and LIMIT long lists.
- If the panel cannot answer the question (forecasts, opinions, data it does not
  hold), decline instead of guessing.
Reply with JSON only: {"sql": "...", "explanation": "..."} or
{"sql": null, "decline": "reason"}."""


def render_prompt(req):
    """The user turn sent to the model, built only from the request dict (so the
    cache key, which hashes the whole request, covers everything the model saw).
    The rules arrive inside req["schema"] (agent.graph.schema_with_values)."""
    parts = ["Tables and columns:", req["schema"], ""]
    if req.get("history"):
        parts.append("Conversation so far (earlier questions and the SQL that answered them):")
        for i, h in enumerate(req["history"], 1):
            parts.append(f"{i}. Q: {h.get('question')}\n   SQL: {h.get('sql')}")
        parts.append("")
    parts.append(f"Question: {req['question']}")
    if req.get("error"):
        parts += ["", f"Your previous SQL (attempt {req.get('attempt', 0)}) was:",
                  str(req.get("prior_sql")),
                  f"It failed with {req['error'].get('code')}: {req['error'].get('detail')}",
                  "Write a corrected query (or decline)."]
    return "\n".join(parts)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)


def parse_reply(text):
    """{"sql", "decline", "explanation"} from the model's text; anything unparseable
    becomes neither sql nor decline, which the check node turns into a repair."""
    try:
        d = json.loads(_FENCE.sub("", (text or "").strip()))
        if not isinstance(d, dict):
            raise ValueError
    except ValueError:
        return {"sql": None, "decline": None, "explanation": "",
                "parse_error": (text or "")[:500]}
    return {"sql": d.get("sql") or None, "decline": d.get("decline") or None,
            "explanation": d.get("explanation") or ""}


def load_key():
    """GEMINI_API_KEY from the environment, else from cs4b/.env."""
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    return os.environ.get("GEMINI_API_KEY")


class GeminiCall:
    """One request -> one Gemini call. Used only in record mode."""

    def __init__(self, model_name, prices, retries=4):
        key = load_key()
        if not key:
            raise RuntimeError("record mode needs GEMINI_API_KEY (environment or cs4b/.env)")
        from google import genai
        self.genai = genai
        self.client = genai.Client(api_key=key)
        self.model_name, self.prices, self.retries = model_name, prices, retries

    def __call__(self, req):
        types = self.genai.types
        cfg = types.GenerateContentConfig(system_instruction=req["system"], temperature=0,
                                          response_mime_type="application/json")
        for i in range(self.retries + 1):
            t0 = time.perf_counter()
            try:
                resp = self.client.models.generate_content(
                    model=self.model_name, contents=render_prompt(req), config=cfg)
                break
            except Exception as e:  # noqa: BLE001  (rate limits on the free tier)
                if i == self.retries or "429" not in str(e) and "503" not in str(e):
                    raise
                time.sleep(10 * (i + 1))
        latency = time.perf_counter() - t0
        u = resp.usage_metadata
        t_in = int(getattr(u, "prompt_token_count", 0) or 0)
        t_out = int((getattr(u, "candidates_token_count", 0) or 0)
                    + (getattr(u, "thoughts_token_count", 0) or 0))
        out = parse_reply(resp.text)
        out.update({"model": self.model_name, "tokens_in": t_in, "tokens_out": t_out,
                    "usd": round(econ.step_usd(t_in, t_out, self.prices["usd_per_mtok_in"],
                                               self.prices["usd_per_mtok_out"]), 8),
                    "latency_s": round(latency, 3), "retries": i,
                    "raw": (resp.text or "")[:2000]})
        return out


def make_model(mode=None, params=PARAMS, call=None):
    """A ReplayClient over outputs/cache. mode defaults to params model.mode (replay).
    call: override the provider (tests pass the kit's stand-in)."""
    mode = mode or params["model"]["mode"]
    if mode not in ("record", "replay"):
        raise ValueError(f"mode must be record or replay, not {mode!r}")
    if mode == "record" and call is None:
        call = GeminiCall(params["model"]["name"], params["prices"])
    return llm.ReplayClient(ROOT / params["model"]["cache_dir"], mode, call=call)
