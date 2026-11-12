"""Separate recorded model cost estimates from explicit monthly assumptions."""
import json
from pathlib import Path
import yaml
from services.agent.run import save


def build(root):
    root = Path(root)
    p = yaml.safe_load((root / 'params.yaml').read_text())
    ec = p['economics']; assumptions = ec['monthly_assumptions']
    suite = json.loads((root / 'reports/evals/dev.json').read_text())
    tasks = [json.loads(l) for l in (root / 'outputs/tasks/dev.jsonl').read_text().splitlines()]
    scenario = json.loads((root / 'outputs/scenario/release_morning.json').read_text())
    mandates = json.loads((root / p['data']['mandates']).read_text())
    current_total = sum(e['usd'] for t in tasks for e in t['model_calls'])
    # Include cached responses from failed attempts; never count a response twice.
    def recorded_cost(pattern):
        responses = {}
        for path in (root / 'evals/recordings').glob(pattern):
            response = json.loads(path.read_text())
            responses[response['provider_response_id']] = response['usd']
        return sum(responses.values())
    total = recorded_cost('suite-dev*/*/responses/*.json')
    scenario_all_attempts = recorded_cost('release-morning*/responses/*.json')
    passed = sum(t['passed'] for t in suite['tasks'])
    cost_per_success = total / passed if passed else None
    if cost_per_success is None:
        raise ValueError('No successful tasks; cannot estimate a completed-task unit cost')
    note_cost = scenario['estimated_model_usd']
    rows = []
    for m in mandates:
        model = note_cost * assumptions['notes_per_mandate_month'] + cost_per_success * assumptions['other_tasks_per_mandate_month']
        review = assumptions['review_hours_per_note'] * assumptions['notes_per_mandate_month'] * ec['analyst_rate_usd']
        infra = assumptions['shared_hosting_usd_per_month'] / len(mandates)
        rows.append({'mandate': m, 'model_usd': model, 'human_review_usd': review,
                     'allocated_hosting_usd': infra, 'total_usd_per_mandate_month': model+review+infra})
    reviews = len({bdc for m in mandates.values() for bdc in m['positions']})
    sensitivity = [{'time_saved_multiplier': k, 'analyst_hours': reviews*ec['analyst_hours_per_review']*k,
                    'gross_time_value_usd': reviews*ec['analyst_hours_per_review']*k*ec['analyst_rate_usd']} for k in [.5, 1, 2]]
    result = {'recorded_suite_model_usd': total, 'current_suite_model_usd': current_total,
              'scenario_all_attempts_model_usd': scenario_all_attempts, 'suite_passed': passed, 'suite_total': len(tasks),
              'model_cost_per_passed_task_including_failed_attempts_usd': cost_per_success,
              'scenario_model_usd': note_cost, 'scenario_process_seconds': scenario['recorded_process_seconds'],
              'replay_model_api_cost_usd': 0, 'monthly_assumptions': assumptions, 'monthly_costs': rows,
              'analyst_sensitivity': sensitivity,
              'illustrative_failure_expected_loss_per_mandate_month_usd': assumptions['illustrative_incident_cost_usd']*assumptions['illustrative_incident_probability_per_mandate_month'],
              'limitations': ['Prices are the recorded model configuration, not a billing statement.',
                  'Development cost includes retained failed attempts; monthly costs therefore use a conservative development-run proxy.',
                  'Successful-task denominator means passed automated dev checks, not independently measured business success.',
                  'Scenario A cost is a proxy for either mandate, not a measured B scenario.',
                  'Hosting, review time, monthly activity and incident probability/severity are assumptions, not observations.',
                  'No measured probability reduction is attributed to approval or isolation controls.',
                  'Analyst time value is gross potential value, not verified savings or profit.']}
    save(root / 'reports/economics/unit_economics.json', result)
    lines = ['mandate,model_usd,human_review_usd,allocated_hosting_usd,total_usd_per_mandate_month']
    for row in rows:
        lines.append(','.join([row['mandate'], *[f"{row[k]:.4f}" for k in list(row)[1:]]]))
    (root / 'reports/economics/mandate_month.csv').write_text('\n'.join(lines)+'\n')
    return result
