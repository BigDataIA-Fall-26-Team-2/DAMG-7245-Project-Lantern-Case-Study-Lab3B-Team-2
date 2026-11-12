"""Run all notebooks in fresh IPython processes, preserving Jupyter cell semantics.

Usage: python tools/run_notebooks.py (uses the mode set in params.yaml).
Notebooks may write lab outputs; run in a disposable checkout for a submission audit.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
CELL_RUNNER = '''
import json, sys
from IPython.core.interactiveshell import InteractiveShell
shell = InteractiveShell.instance()
for index, source in json.load(sys.stdin):
    result = shell.run_cell(source, store_history=False)
    if not result.success:
        print(f"Notebook code cell {index} failed", file=sys.stderr)
        raise SystemExit(1)
'''


def run_notebook(path, root=ROOT):
    notebook = json.loads(Path(path).read_text())
    cells = [(i + 1, ''.join(c['source'])) for i, c in enumerate(notebook['cells']) if c['cell_type'] == 'code']
    result = subprocess.run([sys.executable, '-c', CELL_RUNNER],
        input=json.dumps(cells), cwd=Path(root) / 'notebooks',
        capture_output=True, text=True, env=dict(os.environ, MPLBACKEND='Agg'))
    return result, len(cells)


def main():
    notebooks = sorted((ROOT / 'notebooks').glob('*.ipynb'))
    failed = 0
    for path in notebooks:
        result, count = run_notebook(path)
        failed += result.returncode != 0
        print(f"  {'PASS' if result.returncode == 0 else 'FAIL'}  {path.name} ({count} code cells)", flush=True)
        if result.returncode:
            print((result.stdout + result.stderr)[-4000:])
    print(f'{len(notebooks) - failed}/{len(notebooks)} notebooks run end to end')
    return int(bool(failed))


if __name__ == '__main__':
    raise SystemExit(main())
