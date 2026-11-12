"""Synthetic unit tests are explicitly separate from live-provider acceptance."""
import json
from pathlib import Path
import sys
import urllib.error
import io

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from creditwatch import audit, channel, workspace
from creditwatch.llm import CacheMiss
from services.mcp.server import create_runtime
from services.agent.model import OpenAIProvider, RoutedModel
from services.agent.run import prepare, execute, verify, save

@pytest.fixture
def bundle(tmp_path):
    fx = ROOT / 'data/fixture'
    users = json.loads((fx / 'users.json').read_text())
    mandates = json.loads((fx / 'mandates.json').read_text())
    ws = workspace.fresh_workspace(ROOT / 'agent_seed', tmp_path / 'agent')
    runtime = create_runtime(session=channel.login('priya', 'priya-fixture-token', 'mandate_a', users),
        ledger=audit.Ledger(), mandates=mandates, workspace=ws, outbox=tmp_path/'outbox')
    path = tmp_path/'recording'
    prepare(ROOT, path, runtime)
    manifest = json.loads((path/'manifest.json').read_text())
    manifest['provenance'] = 'synthetic-unit-test'
    save(path/'manifest.json', manifest)
    return path, runtime

class FakeProvider:
    def __init__(self): self.calls=[]
    def __call__(self, request):
        self.calls.append(request)
        tool, args, text = None, {}, 'Synthetic assessment for tests only.'
        if request['phase']=='agent':
            count=sum(m['role']=='tool' for m in request['input']['messages'])
            if count==0: tool,args='mandate_profile',{'scope':'mandate_a'}
            elif count==1: tool,args='bdc_signals',{'scope':'public'}
            else: text='Synthetic client note for unit tests only.'
        return {'tool':tool, 'args_json':json.dumps(args), 'text':text,
                'rationale':'Test decision', 'tokens_in':100, 'tokens_out':20,
                'usd':0.001, 'provider_response_id':'synthetic-'+str(len(self.calls))}

def record_synthetic(bundle):
    path,runtime=bundle
    provider=FakeProvider()
    result=execute(path,'record',provider,runtime)
    save(path/'recorded.json',result)
    return path,provider,result

def test_record_then_twice_replay_without_network(bundle,monkeypatch):
    path,provider,result=record_synthetic(bundle)
    assert len(provider.calls)==5
    def blocked(*a,**k):raise AssertionError('Replay attempted network access')
    monkeypatch.setattr('urllib.request.urlopen',blocked)
    report=verify(path)
    assert report['identical'] and report['provider_calls_during_replay']==0
    assert report['provenance']=='synthetic-unit-test'
    assert (path/'recorded.json').read_bytes()==(path/'replay-1.json').read_bytes()==(path/'replay-2.json').read_bytes()
    assert len(provider.calls)==5

def test_small_model_routes_assessments(bundle):
    path,provider,_=record_synthetic(bundle)
    config=json.loads((path/'manifest.json').read_text())['models']
    assert [r['phase'] for r in provider.calls[:2]]==['triage','materiality']
    assert all(r['model']==config['small']['model'] for r in provider.calls[:2])
    assert all(r['model']==config['main']['model'] for r in provider.calls[2:])
    assert 'materiality' in provider.calls[2]['input']['brief']

def test_unrecorded_request_fails_closed(bundle):
    path,_=bundle
    with pytest.raises(CacheMiss):execute(path,'replay')

def test_context_change_invalidates_cache(bundle):
    path,_,_=record_synthetic(bundle)
    m=json.loads((path/'manifest.json').read_text());m['context']+=' changed'
    save(path/'manifest.json',m)
    with pytest.raises(CacheMiss):execute(path,'replay')

def test_assessment_budget_stops_before_agent(bundle):
    path,runtime=bundle
    m=json.loads((path/'manifest.json').read_text());m['budget']['usd_cap_per_task']=0.0001
    save(path/'manifest.json',m)
    provider=FakeProvider()
    with pytest.raises(RuntimeError,match='budget'):execute(path,'record',provider,runtime)
    assert len(provider.calls)==1

def test_provider_posts_structured_request_and_counts_usage(monkeypatch):
    seen=[]
    def post(req,timeout):
        seen.append(json.loads(req.data))
        response={'status':'completed','id':'resp-test','usage':{'input_tokens':100,'output_tokens':20},
                  'output':[{'content':[{'type':'output_text','text':json.dumps({'tool':None,'args_json':'{}','text':'Done','rationale':'Complete'})}]}]}
        return io.BytesIO(json.dumps(response).encode())
    monkeypatch.setattr('urllib.request.urlopen',post)
    provider=OpenAIProvider('test-key-not-real')
    result=provider({'model':'test-model','instructions':'test','input':{},'max_output_tokens':100,
                     'prices':{'input':1,'output':2}})
    assert result['usd']==0.00014
    assert result['tokens_in']==100
    assert seen[0]['store'] is False
    assert seen[0]['text']['format']['strict'] is True
    assert 'test-key-not-real' not in json.dumps(result)

def test_provider_rejects_incomplete_response(monkeypatch):
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**k:io.BytesIO(b'{"status":"incomplete"}'))
    with pytest.raises(RuntimeError,match='incomplete'):
        OpenAIProvider('test')({'model':'x','instructions':'x','input':{},'max_output_tokens':1,'prices':{}})

def test_real_recording_acceptance(tmp_path,monkeypatch):
    import shutil
    source=ROOT/'evals/recordings/dev-01'
    if not (source/'recorded.json').exists():
        pytest.skip('Live OpenAI recording pending: run python -m services.agent.run record')
    path=tmp_path/'real-recording'
    shutil.copytree(source,path)
    assert json.loads((path/'manifest.json').read_text())['provenance']=='openai-live'
    def blocked(*a,**k):raise AssertionError('Live acceptance replay attempted network')
    monkeypatch.setattr('urllib.request.urlopen',blocked)
    assert verify(path)['identical']


@pytest.mark.parametrize("split_blocks", [False, True])
def test_parser_handles_identical_repeated_json(split_blocks):
    from services.agent.model import parse_decision
    value={"tool":None,"args_json":"{}","text":"Done","rationale":"Complete"}
    text=json.dumps(value)
    content=([{"type":"output_text","text":text}]*2 if split_blocks
             else [{"type":"output_text","text":text+text}])
    assert parse_decision({"output":[{"content":content}]}).text=="Done"


def test_parser_uses_final_message_not_concatenated_messages():
    from services.agent.model import parse_decision
    def msg(text,phase):
        return {"type":"message","role":"assistant","phase":phase,"content":[{"type":"output_text","text":text}]}
    value={"tool":None,"args_json":"{}","text":"Done","rationale":"Complete"}
    assert parse_decision({"output":[msg("Working...","commentary"),msg(json.dumps(value),"final_answer")]}).text=="Done"


@pytest.mark.parametrize("tail", ["garbage", '{"tool":null,"args_json":"{}","text":"Different","rationale":"Other"}'])
def test_parser_rejects_malformed_or_conflicting_decisions(tail):
    from services.agent.model import parse_decision
    value={"tool":None,"args_json":"{}","text":"Done","rationale":"Complete"}
    with pytest.raises(RuntimeError):
        parse_decision({"output":[{"content":[{"type":"output_text","text":json.dumps(value)+tail}]}]})
