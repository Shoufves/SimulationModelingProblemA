"""Check executed v13 allocation, commissioning, cash and operation ledgers."""
import json
from math import fsum, isclose
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from energy_model.q2.io import csvout, dump, sha


def execute():
    folder = ROOT / 'outputs/q2/historical_candidate_v13'
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    model, result = [read(folder / f) for f in ('selected_model.json', 'result.json')]
    options = {o['id']: o for o in model['investment_options']}
    initial_money = fsum(a['cash'] for a in model['agents']) + fsum(model['other_accounts'].values())
    checks, allocations = [], []
    max_money = max_queue = max_balance = 0.
    for annual in result['annual']:
        year = annual['year']
        policy = next(i['policy'] for i in result['information'] if i['year'] == year)
        approved = [r for r in result['actions'] if r['year'] == year and 'approved_units' in r]
        allocated = [r for r in result['actions'] if r['year'] == year and 'allocated_request_units' in r]
        amounts = {r['option']: r['approved_units'] for r in approved}
        for row in allocated:
            quantity = row['allocated_request_units']
            assert 0 <= quantity <= row['feasible_request_units'] + 1e-8
            assert row['feasible_request_units'] <= row['original_request_units'] + 1e-8
            assert isclose(quantity, row['feasible_request_units'] * row['common_allocation_fraction'], abs_tol=1e-8)
            assert isclose(quantity, amounts.get(row['option'], 0.), abs_tol=1e-7, rel_tol=1e-8)
            allocations.append(dict(row, approved_units=amounts.get(row['option'], 0.)))
        construction = fsum(r['approved_units'] for r in approved)
        connection = fsum(r['approved_units'] * options[r['option']]['connection_per_unit'] for r in approved)
        assert construction <= policy['construction_units_limit'] + 1e-6
        assert connection <= policy['connection_limit'] + 1e-6
        money = fsum(annual['agent_cash'].values()) + fsum(annual['accounts'].values())
        escrow = fsum(p['remaining_cost'] for p in result['projects'] if p['year'] == year and p['state'] == 'building')
        max_money = max(max_money, abs(money - initial_money))
        max_queue = max(max_queue, abs(escrow - annual['accounts']['escrow']))
        assert isclose(money, initial_money, abs_tol=1e-6, rel_tol=1e-8)
        assert isclose(escrow, annual['accounts']['escrow'], abs_tol=1e-6, rel_tol=1e-8)
        operation = next(r['result'] for r in result['operations'] if r['year'] == year)
        balance = max(abs(r['residual_mwh']) for r in operation['balances'])
        max_balance = max(max_balance, balance)
        assert balance <= 1e-6
        assert operation['status'] == 'optimal'
        checks.append(dict(year=year, construction_used=construction, construction_limit=policy['construction_units_limit'],
            connection_used=connection, connection_limit=policy['connection_limit'], cash_error=money - initial_money,
            queue_escrow_error=escrow - annual['accounts']['escrow'], max_carrier_balance_residual_mwh=balance,
            wind_approved_mw=amounts.get('wind_build', 0.)))
    for p in result['projects']:
        assert p['online_year'] == p['applied_year'] + p['lead_years']
        for asset in result['assets']:
            if asset['id'] == p['id']:
                assert asset['year'] >= p['online_year'] > p['applied_year']
    old = read(ROOT / 'outputs/q2/activity_regressions.json')
    regression = {}
    for name, binding in old['engineering_files'].items():
        current = sha(ROOT / 'outputs/q2/allocation_engineering_regression' / name)
        assert current == binding['original_sha256'], name
        regression[name] = dict(byte_identical=True, sha256=current)
    csvout(ROOT / 'outputs/q2/allocation_year_checks.csv', checks)
    csvout(ROOT / 'outputs/q2/allocation_request_checks.csv', allocations)
    report = dict(all_checks_passed=True, years=len(checks), allocation_requests=len(allocations),
        no_same_year_commissioning=True, maximum_money_error=max_money,
        maximum_queue_escrow_error=max_queue, maximum_carrier_balance_error_mwh=max_balance,
        engineering_identical_count=len(regression), engineering_files=regression,
        wind_receives_positive_allocation_2019_2024=all(r['wind_approved_mw'] > 0 for r in checks if r['year'] >= 2019),
        national_acceptance=False, model_sha256=sha(folder / 'selected_model.json'), result_sha256=sha(folder / 'result.json'))
    dump(ROOT / 'outputs/q2/allocation_checks.json', report)
    print(json.dumps({k: report[k] for k in ('years', 'allocation_requests', 'engineering_identical_count', 'all_checks_passed')}))
    return report


if __name__ == '__main__':
    execute()
