"""Verify working skill locks, evidence preservation and deterministic CLI output."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from creditwatch import skills, signals, panel
from tools.check_skills import measure


def load(path):
    spec=importlib.util.spec_from_file_location('skill_helper',path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod


def test_working_skills_complete_locked_and_fit_budget():
    folder,index,report=measure(ROOT)
    assert report['skill_count']>=6 and len(report['scripted_skills'])>=2
    assert report['index_fits_budget']
    skills.verify(folder,json.loads((folder/'skills.lock').read_text()))
    saved=json.loads((ROOT/'reports/skills/token_savings.json').read_text())
    assert saved==report


@pytest.mark.parametrize('relative',['signal-explainer/SKILL.md','signal-explainer/scripts/explain_signals.py','bdc-quarter-review/scripts/signal_table.py'])
def test_working_lock_detects_instruction_and_script_edits(tmp_path,relative):
    dest=tmp_path/'skills';shutil.copytree(ROOT/'agent/skills',dest)
    pins=json.loads((dest/'skills.lock').read_text())
    target=dest/relative;target.write_text(target.read_text()+'\n# unexpected edit\n')
    with pytest.raises(RuntimeError,match='skill hash mismatch'):skills.verify(dest,pins)


@pytest.mark.parametrize('helper',['bdc-quarter-review/scripts/signal_table.py','signal-explainer/scripts/explain_signals.py'])
def test_script_cli_is_deterministic_and_preserves_citations(tmp_path,helper):
    params=yaml.safe_load((ROOT/'params.yaml').read_text())
    frame=panel.load_panel(ROOT/'data/fixture/panel_2p.csv')
    rows=json.loads(signals.find_signals(frame,params['heartbeat']['materiality']).to_json(orient='records'))
    path=tmp_path/'signals.json';path.write_text(json.dumps(rows))
    script=ROOT/'agent/skills'/helper
    def run():return subprocess.check_output([sys.executable,str(script),str(path)])
    first=run();assert run()==first
    path.write_text(json.dumps(list(reversed(rows))))
    assert run()==first
    text=first.decode()
    for row in rows:
        assert row['adsh'] in text and str(row['prior_row']) in text and str(row['row']) in text
    assert len(text.splitlines())==len(rows)+2


def sample(**changes):
    return {'name':'BDC','identifier':'Loan | A\ncontinued','adsh':'0009000012-26-000121',
            'row':'101','prior_row':'501','rule':'MARKDOWN','before':99.0,'after':93.5,**changes}


def explainer():return load(ROOT/'agent/skills/signal-explainer/scripts/explain_signals.py')


def test_explainer_calculates_units_and_escapes_cells():
    text=explainer().render([sample(),sample(rule='PIK_UP',before=1,after=3),
                          sample(rule='EXTENDED',before='2024-02-28',after='2024-03-01')])
    assert '5.50 points' in text and '2.00 percentage points' in text and '2 days later' in text
    assert 'Loan \\| A continued' in text


@pytest.mark.parametrize('changes',[{'before':None},{'after':float('nan')},{'after':100},
    {'rule':'PIK_UP','before':3,'after':1},{'rule':'UNKNOWN'},{'prior_row':''},
    {'rule':'EXTENDED','before':'2025-02-30','after':'2026-01-01'}])
def test_explainer_rejects_bad_or_unsupported_evidence(changes):
    with pytest.raises(ValueError):explainer().render([sample(**changes)])
