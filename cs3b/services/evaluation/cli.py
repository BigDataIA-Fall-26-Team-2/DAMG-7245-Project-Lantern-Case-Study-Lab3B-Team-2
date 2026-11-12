"""lantern eval run --suite dev|variant --mode record|replay"""
import argparse
import json
import os
from pathlib import Path
from services.evaluation.runner import ROOT, DEV_CONTROLS, load_tasks, prepare, execute, verify
from services.evaluation.grading import grade
from creditwatch.llm import CacheMiss
from services.agent.model import OpenAIProvider
from services.agent.run import save


def run_suite(root, suite, mode, provider=None, token=None):
    root = Path(root)
    tasks = load_tasks(root, suite)
    output, grades = [], []
    controls_path = root / f'evals/tasks/{suite}_controls.json'
    controls = json.loads(controls_path.read_text()) if controls_path.exists() else DEV_CONTROLS if suite == 'dev' else {}
    for task in tasks:
        print(f"{mode}: {task['task_id']}", flush=True)
        bundle = root / 'evals/recordings' / ('suite-' + suite + '-v2') / task['task_id']
        if mode == 'record':
            prepare(root, bundle, task, token, controls.get(task['task_id'], {}))
            execute(root, bundle, 'record', provider)
        if not (bundle / 'manifest.json').exists():
            raise FileNotFoundError('Missing recording for ' + task['task_id'] + '; record it first')
        m = json.loads((bundle / 'manifest.json').read_text())
        if m['task'] != task:
            raise ValueError('Suite task differs from frozen recording')
        result = verify(root, bundle)
        journal = json.loads((bundle / 'journal.json').read_text())
        output.append(result)
        grades.append(grade(task, result, m, journal))
    destination = root / 'outputs/tasks' / (suite + '.jsonl')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in output))
    summary = {'suite': suite, 'mode': mode, 'tasks': grades,
               'passed': sum(r['passed'] for r in grades), 'total': len(grades),
               'replay_provider_calls': 0, 'replay_server_calls': 0,
               'checks_source': 'Starter Appendix G fields/checker and available task expectations; separate Appendix G document unavailable'}
    save(root / 'reports/evals' / (suite + '.json'), summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    evaluation = commands.add_parser('eval').add_subparsers(dest='eval_command', required=True)
    run = evaluation.add_parser('run')
    run.add_argument('--suite', choices=['dev', 'variant'], required=True)
    run.add_argument('--mode', choices=['record', 'replay'], default='replay')
    scenario = commands.add_parser('scenario')
    scenario.add_argument('--mode', choices=['record', 'replay'], default='replay')
    commands.add_parser('economics')
    args = parser.parse_args()
    provider = token = None
    if getattr(args, 'mode', None) == 'record':
        from dotenv import load_dotenv
        load_dotenv(ROOT / '.env', override=False, interpolate=False)
        key, token = os.environ.get('OPENAI_API_KEY'), os.environ.get('CREDITWATCH_SESSION_TOKEN')
        if not key or not token:
            parser.error('Set the OpenAI key and session token in local .env')
        provider = OpenAIProvider(key)
    try:
        if args.command == 'eval':
            result = run_suite(ROOT, args.suite, args.mode, provider, token)
        elif args.command == 'scenario':
            from services.evaluation.scenario import run
            result = run(ROOT, args.mode, token, provider)
        else:
            from services.evaluation.economics import build
            result = build(ROOT)
    except (FileNotFoundError, ValueError, RuntimeError, CacheMiss) as exc:
        parser.exit(2, str(exc) + '\n')
    print(json.dumps(result, indent=2))
    if args.command == 'eval' and result['passed'] != result['total']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
