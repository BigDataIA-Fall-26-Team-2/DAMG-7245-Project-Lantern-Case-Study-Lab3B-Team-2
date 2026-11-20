"""API tests run in replay mode against data/panel.sqlite (the real panel).

If the database is missing it is built by the existing tools/build_db.py in a
subprocess: the API itself never opens the database.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

CS4B = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CS4B))
os.environ.pop("GEMINI_API_KEY", None)           # never call Gemini from tests

import yaml  # noqa: E402

import api.service as _svc  # noqa: E402

_svc.load_key = lambda: None                     # ...even if cs4b/.env holds a key

PARAMS = yaml.safe_load((CS4B / "params.yaml").read_text())
DB = CS4B / PARAMS["data"]["db"]
if not DB.exists():
    subprocess.run([sys.executable, "tools/build_db.py"], cwd=CS4B, check=True)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from api.main import app
    with TestClient(app) as c:                   # runs the lifespan: agent built once
        yield c


@pytest.fixture(scope="session")
def recorded():
    from askpanel import questions
    return {q["id"]: q for q in questions.load(CS4B / "questions/questions.yaml")}
