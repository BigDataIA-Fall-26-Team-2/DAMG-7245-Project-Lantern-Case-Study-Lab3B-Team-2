"""Notebook checks must support Jupyter syntax and propagate cell failures."""
import json
from tools.run_notebooks import run_notebook


def notebook(tmp_path, sources):
    (tmp_path / 'notebooks').mkdir()
    path = tmp_path / 'notebooks/example.ipynb'
    path.write_text(json.dumps({'cells': [{'cell_type': 'code', 'source': [s]} for s in sources]}))
    return path


def test_jupyter_await_display_and_shared_cell_state(tmp_path):
    path = notebook(tmp_path, ['import asyncio\nx = await asyncio.sleep(0, result=42)', 'assert x == 42\ndisplay(x)'])
    result, count = run_notebook(path, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert count == 2 and '42' in result.stdout


def test_cell_failure_stops_notebook(tmp_path):
    path = notebook(tmp_path, ['raise ValueError("expected failure")', 'print("SHOULD_NOT_RUN")'])
    result, _ = run_notebook(path, tmp_path)
    assert result.returncode != 0
    assert 'SHOULD_NOT_RUN' not in result.stdout
