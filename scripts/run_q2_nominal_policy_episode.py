"""Run all seven predeclared tariff/currency cases and reconcile cohort cash."""
import argparse
import json
from pathlib import Path

import run_q2_historical_candidate as history
from run_q2_deployment_ablation import technology_rows
from run_q2_solar_ablation import constraint_rows
from energy_model.q2.contracts import active, settlement_price, price_adjustment
from energy_model.q2.io import csvout, dump, local_path, sha

ROOT = history.ROOT


def cohort_rows(case, model, result):
    """Independently reconstruct delivered MWh and signed support by cohort."""
    rows = []
    for operation in result['operations']:
        year = operation['year']
        policy = next(r['policy'] for r in result['information'] if r['year'] == year)
        operating = [a for a in result['assets'] if a['year'] == year and a['state'] == 'operating']
        for asset in operating:
            contract = asset.get('revenue_contract')
            if contract is None or not active(contract, year):
                continue
            component = next(p for p in model['operation']['processes'] if p['id'] == asset['component'])
            denominator = sum(a['quantity'] for a in operating if a['kind'] == 'process' and a['component'] == asset['component'])
            activity = sum(f['value'] * f['annual_weight'] for f in operation['result']['flows']
                           if f['kind'] == 'process' and f['id'] == asset['component'])
            output = activity * component['outputs'][contract['output_carrier']] * asset['quantity'] / denominator
            transfers = [r for r in result['cash'] if r['year'] == year and r.get('asset') == asset['id']
                         and r.get('contract') == contract['id']]
            paid = sum(r['amount'] for r in transfers if r['reason'] == 'operating_contract_support')
            clawback = sum(r['amount'] for r in transfers if r['reason'] == 'operating_contract_clawback')
            expected = output * price_adjustment(contract, policy, year)
            residual = paid - clawback - expected
            if abs(residual) > 1e-8 * max(1., abs(expected)):
                raise ValueError('Cohort output/revenue reconciliation failed')
            rows.append(dict(case=case, year=year, asset=asset['id'], capacity_MW=asset['quantity'],
                quote_currency=contract.get('nominal_currency', 'million_USD_2008'), quoted_per_MWh=contract['price_per_mwh'],
                realized_price_million_USD2008_per_MWh=settlement_price(contract, policy, year),
                common_price_million_USD2008_per_MWh=policy['node_prices'][contract['output_carrier']],
                delivered_MWh=output, support_million_USD2008=paid, clawback_million_USD2008=clawback,
                independent_signed_support=expected, cash_residual=residual,
                physical_allocation='Identical process cohorts share realized dispatch by operating capacity, as in the engine.'))
    return rows


def execute(output_relative):
    manifest_path = ROOT / 'workflow/q2_candidates/nominal_policy_episode/manifest.json'
    manifest, data = history.load_frozen(manifest_path)
    if manifest.get('study_kind') != 'fixed_policy_episode_no_calibration' or len(data['episode']['cases']) != 7:
        raise ValueError('Expected the complete predeclared seven-case episode')
    out = local_path(ROOT, output_relative)
    if not out.is_relative_to((ROOT / 'outputs/q2').resolve()) or out == (ROOT / 'outputs/q2').resolve() or out.exists():
        raise ValueError('Use a fresh outputs/q2 child directory')
    out.mkdir(parents=True)
    dump(out / 'attempt.json', dict(status='running', national_acceptance=False))
    try:
        metrics, quality, losses, activity, constraints, cohorts, valuations, checks = [], [], [], [], [], [], [], []
        for case in data['episode']['cases']:
            name = case['id']
            model = data['structural_models'][name]
            result = history.EnergyModel(model).run()
            values = history.metric_rows(result, data['definitions'])
            fit = history.compare(data['observations'], values, data['experiment']['targets'], data['experiment']['windows'])
            loss, parts = history.loss(fit, data['experiment']['targets'])
            baselines = history.baseline_comparisons(data['observations'], data['experiment']['targets'], data['experiment']['windows'])
            check = history.historical_quality({'history_fit': fit, 'baselines': baselines}, data['experiment']['targets'],
                                              data['acceptance']['historical_quality'], data['experiment']['windows'])
            dump(out / (name + '.json'), dict(case=case, result=result, training_loss_diagnostic_only=loss,
                                            historical_quality=check))
            metrics.extend(dict(case=name, **r) for r in values)
            quality.extend(dict(case=name, **r) for r in check['targets'])
            losses.extend(dict(case=name, **r) for r in parts)
            activity.extend(dict(case=name, **r) for r in technology_rows(model, result))
            constraints.extend(dict(case=name, **r) for r in constraint_rows(model, result))
            cohort = cohort_rows(name, model, result)
            cohorts.extend(cohort)
            for decision in result['actions']:
                if decision.get('option') == 'solar_new_build' and 'investment_npv' in decision:
                    valuations.append(dict(case=name, **decision))
            contracts = [p for p in result['projects'] if 'revenue_contract' in p]
            if any(p['applied_year'] != 2015 or p['online_year'] != 2016 for p in contracts):
                raise ValueError('Episode awarded an unintended application cohort')
            checks.append(dict(case=name, training_loss=loss, selected_for_national_use=False,
                awarded_project_ids=sorted({p['id'] for p in contracts}),
                cumulative_support=sum(r['support_million_USD2008'] for r in cohort),
                maximum_cohort_cash_residual=max((abs(r['cash_residual']) for r in cohort), default=0.),
                failed_numeric_indicators=[r['indicator'] for r in check['targets'] if not r['passed']]))
        for name, rows in [('metrics', metrics), ('quality', quality), ('training_loss_parts', losses),
                           ('technology_activity', activity), ('constraint_usage', constraints),
                           ('cohort_cash', cohorts), ('investment_valuations', valuations)]:
            csvout(out / (name + '.csv'), rows)
        dump(out / 'summary.json', dict(scope=data['episode']['scope'], cases=checks, national_acceptance=False,
            no_calibration_or_case_selection=True, all_cases_executed=True,
            interpretation='Only a hypothetical eligible 2015 PV application cohort changes. Each geographic tariff is a separate conditional assignment; none is a national average. Realized currency factors enter current-year snapshots; current conversion is held constant in investment valuation. Partial historical episode cannot establish the complete policy effect or solve national input gaps.'))
        paths = [Path(__file__), ROOT / 'scripts/build_q2_nominal_policy_episode.py', ROOT / 'scripts/run_q2_historical_candidate.py',
                 ROOT / 'scripts/run_q2_deployment_ablation.py', ROOT / 'scripts/run_q2_solar_ablation.py',
                 *sorted((ROOT / 'src/energy_model/q2').glob('*.py'))]
        dump(out / 'run_manifest.json', dict(status='policy_episode_executed', manifest_path=manifest_path.relative_to(ROOT).as_posix(),
            manifest_sha256=sha(manifest_path), code_hashes={p.relative_to(ROOT).as_posix(): sha(p) for p in paths},
            outputs={p.name: sha(p) for p in sorted(out.iterdir()) if p.name != 'attempt.json'}, national_acceptance=False))
        dump(out / 'attempt.json', dict(status='policy_episode_executed', national_acceptance=False))
        print('Seven paired trajectories executed; cohort currency/output/cash reconciled; no case selection')
        return 0
    except Exception as exc:
        dump(out / 'attempt.json', dict(status='failed', reason=str(exc), national_acceptance=False))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    raise SystemExit(execute(parser.parse_args().output_dir))
