"""Execute a frozen material-use partition; never score its partial carbon account."""
import argparse
from copy import deepcopy
import json
from math import fsum, isclose, prod
from pathlib import Path

import build_q2_nonenergy_episode as builder
import run_q2_historical_candidate as history
from energy_model.q2.io import csvout, dump, local_path, sha

ROOT = history.ROOT
PARENT_RESULT = 'outputs/q2/historical_candidate_v10_comparison/shared_construction_connection_pvqueue_2.json'
PARTIAL_CARBON = 'partial_energy_combustion_proxy_after_material_partition'


def require_close(actual, expected, label):
    if not isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-6):
        raise ValueError(f'{label}: {actual} != {expected}')
    return actual - expected


def flow_totals(operation):
    totals = {}
    for row in operation['result']['flows']:
        key = row['kind'], row['id']
        totals.setdefault(key, []).append(row['value'] * row['annual_weight'])
    return {key: fsum(values) for key, values in totals.items()}


def metric_definitions(definitions, split):
    copied = deepcopy(definitions)
    if split:
        carbon = next(d for d in copied if d['id'] == 'gcb_fuel_co2')
        carbon['id'] = PARTIAL_CARBON
        carbon['boundary'] = ('Partial effective-coefficient energy-combustion proxy; reported material '
                              'uses excluded. Material oxidation, process and disposal emissions unresolved. '
                              'Not GCB inventory, net national CO2, storage or avoided emissions.')
    return copied


def initial_checks(parent, model):
    if parent['agents'] != model['agents'] or parent['other_accounts'] != model['other_accounts']:
        raise ValueError('Partition must not create or redistribute opening money')
    checks = []
    for carrier in builder.PRODUCTS:
        def amounts(config):
            op = config['operation']
            devices = [d for d in op['devices'] if d['node'] == carrier]
            services = {s['id']: s for s in op['services']}
            demand = fsum(d * w / device['service_per_mwh'] for device in devices
                          for d, w in zip(services[device['service']]['demand'], op['annual_weights']))
            capacity = fsum(d['input_capacity_mw'] * a['quantity'] for d in devices
                            for a in config['assets'] if a['kind'] == 'device' and
                            a['component'] == d['id'] and a['state'] == 'operating')
            return demand, capacity
        original, split = amounts(parent), amounts(model)
        checks.append(dict(carrier=carrier, original_demand_MWh=original[0], split_demand_MWh=split[0],
            demand_residual_MWh=require_close(split[0], original[0], 'Opening carrier demand'),
            original_capacity_MW=original[1], split_capacity_MW=split[1],
            capacity_residual_MW=require_close(split[1], original[1], 'Opening carrier capacity')))
    return checks


def material_rows(case, model, result, mappings):
    rows = []
    base_year = model['start_year']
    for operation in result['operations']:
        year, op = operation['year'], operation['input']
        totals = flow_totals(operation)
        policy = next(r['policy'] for r in result['information'] if r['year'] == year)
        gdp_ratio = prod(1 + model['gdp_growth'][str(y)] for y in range(base_year + 1, year + 1))
        for item in mappings:
            identity = item['id']
            service = next(s for s in op['services'] if s['id'] == identity)
            device = next(d for d in op['devices'] if d['service'] == identity)
            expected = item['input_MWh_LHV'] * gdp_ratio ** model['demand_drivers'][identity]['gdp_elasticity']
            requested = fsum(d * w for d, w in zip(service['demand'], op['annual_weights']))
            demand_error = require_close(requested, expected, 'Material demand/GDP reconstruction')
            delivered = totals['device', device['id']]
            shortfall = operation['result']['service_shortfalls'][identity]
            balance_error = require_close(delivered + shortfall, requested, 'Material supplied plus unmet')
            transactions = [t for t in result['cash'] if t['year'] == year and
                            t['reference'] == 'device:' + device['id']]
            purchase = fsum(t['amount'] for t in transactions if t['reason'] == 'end_use_purchase')
            sales = fsum(t['amount'] for t in transactions if t['reason'] == 'service_sale')
            expected_purchase = delivered * policy['node_prices'][item['carrier']]
            expected_sales = delivered * policy['service_prices'][identity]
            purchase_error = require_close(purchase, expected_purchase, 'Material fuel purchase')
            sales_error = require_close(sales, expected_sales, 'Material accounting revenue')
            for t in transactions:
                if ((t['reason'] == 'end_use_purchase' and (t['payer'], t['payee']) != (item['owner'], 'clearing')) or
                    (t['reason'] == 'service_sale' and (t['payer'], t['payee']) != ('external_economy', item['owner']))):
                    raise ValueError('Material cash assigned to wrong owner/account')
            if device['gross_co2_t_per_mwh'] != 0 or device['liability_co2_t_per_mwh'] != 0:
                raise ValueError('Material sink must remain outside this partial combustion proxy')
            rows.append(dict(case=case, year=year, material=identity, carrier=item['carrier'], owner=item['owner'],
                requested_MWh_LHV=requested, independently_expected_MWh_LHV=expected,
                supplied_MWh_LHV=delivered, unmet_MWh_LHV=shortfall, demand_residual_MWh=demand_error,
                supply_residual_MWh=balance_error, purchase_million_USD2008=purchase,
                accounting_revenue_million_USD2008=sales, purchase_residual=purchase_error, sales_residual=sales_error,
                excluded_parent_formula_proxy_t=delivered * item['excluded_combustion_proxy_t_per_MWh'],
                actual_material_emissions_t=None, actual_retained_carbon_t=None, removal_credit_t=0.,
                boundary='Material energy content, not useful energy service. Revenue is an inherited modeling assumption. Excluded proxy is not observed carbon, storage or abatement.'))
    return rows


def carrier_rows(case, result):
    rows = []
    for operation in result['operations']:
        op, totals = operation['input'], flow_totals(operation)
        for carrier in builder.PRODUCTS:
            source = fsum(totals['source', s['id']] for s in op['sources'] if s['node'] == carrier)
            conversion_output = fsum(totals['process', p['id']] * p['outputs'].get(carrier, 0.) for p in op['processes'])
            conversion_input = fsum(totals['process', p['id']] * p['inputs'].get(carrier, 0.) for p in op['processes'])
            uses = [d for d in op['devices'] if d['node'] == carrier]
            material = fsum(totals['device', d['id']] for d in uses if d['service'].startswith('nonenergy_'))
            residual = fsum(totals['device', d['id']] for d in uses if not d['service'].startswith('nonenergy_'))
            # This fixed episode has no fossil-fuel stores or fossil-carrying edges.
            if any(s['node'] == carrier for s in op['stores']):
                raise ValueError('Carrier checker requires separate storage accounting')
            error = require_close(source + conversion_output, conversion_input + material + residual, 'Fossil carrier balance')
            rows.append(dict(case=case, year=operation['year'], carrier=carrier, supplied_MWh=source,
                conversion_output_MWh=conversion_output, conversion_input_MWh=conversion_input,
                material_MWh=material, other_end_use_MWh=residual, balance_residual_MWh=error))
    return rows


def paired_control(parent, split, material):
    rows = []
    for a, b in zip(parent['operations'], split['operations']):
        if a['year'] != b['year']:
            raise ValueError('Control years differ')
        before, after = flow_totals(a), flow_totals(b)
        errors = [require_close(after[key], val, 'Same-growth source/process flow')
                  for key, val in before.items() if key[0] in ('source', 'process')]
        year = a['year']
        aa = next(r for r in parent['annual'] if r['year'] == year)
        bb = next(r for r in split['annual'] if r['year'] == year)
        cash_before = fsum([*aa['agent_cash'].values(), *aa['accounts'].values()])
        cash_after = fsum([*bb['agent_cash'].values(), *bb['accounts'].values()])
        cash_error = require_close(cash_after, cash_before, 'Same-growth whole-system money')
        excluded = fsum(r['excluded_parent_formula_proxy_t'] for r in material if r['year'] == year)
        carbon_error = require_close(bb['gross_energy_co2_t'] + excluded, aa['gross_energy_co2_t'], 'Partial carbon arithmetic')
        if aa['captured_co2_t'] != 0 or bb['captured_co2_t'] != 0:
            raise ValueError('No carbon capture allowed in the partition control')
        cost_error = require_close(bb['total_resource_cost'], aa['total_resource_cost'], 'Same-growth resource cost')
        rows.append(dict(year=year, maximum_source_process_residual_MWh=max(map(abs, errors)),
            whole_system_cash_residual=cash_error, resource_cost_residual=cost_error,
            partial_plus_excluded_proxy_residual_t=carbon_error, excluded_formula_proxy_t=excluded,
            actual_material_emissions_t=None, abatement_claim=False))
    return rows


def load_episode():
    # Rebuild validates scoped source records and exact derivation, not just JSON hashes.
    builder.freeze()
    manifest_path = ROOT / builder.DIRECTORY / 'manifest.json'
    manifest, data = history.load_frozen(manifest_path)
    cases = data['episode']['cases']
    if (manifest.get('study_kind') != 'fixed_nonenergy_partition_no_calibration' or
            len(cases) != 29 or len({c['id'] for c in cases}) != 29 or
            set(data['structural_models']) != {c['id'] for c in cases} or
            data['episode']['carbon_target_comparison_admitted'] is not False):
        raise ValueError('Expected all 29 predeclared material-partition cases')
    reference = json.loads((ROOT / PARENT_RESULT).read_text(encoding='utf-8'))['result']
    return manifest_path, data, reference


def execute(output_relative):
    manifest_path, data, reference = load_episode()
    out = local_path(ROOT, output_relative)
    if not out.is_relative_to((ROOT / 'outputs/q2').resolve()) or out == (ROOT / 'outputs/q2').resolve() or out.exists():
        raise ValueError('Use a fresh outputs/q2 child directory')
    out.mkdir(parents=True)
    dump(out / 'attempt.json', dict(status='running', national_acceptance=False))
    try:
        metrics, material, carriers, opening, summaries = [], [], [], [], []
        parent_result, paired = None, None
        for case in data['episode']['cases']:
            name = case['id']
            model = data['structural_models'][name]
            result = history.EnergyModel(model).run()
            split = name != 'v10_control'
            if not split:
                if result != reference:
                    raise ValueError('Exact retained v10 control ledger regression')
                parent_result = result
            opening.extend(dict(case=name, **r) for r in initial_checks(data['model'], model))
            rows = material_rows(name, model, result, data['initialization']['material_mappings']) if split else []
            material.extend(rows)
            carriers.extend(carrier_rows(name, result))
            if name == 'same_growth_split':
                paired = paired_control(parent_result, result, rows)
            metrics.extend(dict(case=name, **r) for r in history.metric_rows(result, metric_definitions(data['definitions'], split)))
            dump(out / (name + '.json'), dict(case=case, result=result,
                carbon_account_boundary=PARTIAL_CARBON if split else 'unchanged_parent_GCB_effective_proxy',
                actual_material_emissions_t=None, national_acceptance=False))
            summaries.append(dict(case=name, years=len(result['annual']),
                maximum_material_shortfall_MWh=max((r['unmet_MWh_LHV'] for r in rows), default=0.),
                maximum_demand_residual_MWh=max((abs(r['demand_residual_MWh']) for r in rows), default=0.),
                maximum_cash_reconciliation_residual=max((abs(r['purchase_residual']) for r in rows), default=0.),
                selected_for_national_use=False))
        for name, rows in [('metrics', metrics), ('material_accounts', material), ('carrier_accounts', carriers),
                           ('opening_conservation', opening), ('same_growth_control', paired)]:
            csvout(out / (name + '.csv'), rows)
        dump(out / 'summary.json', dict(scope=data['episode']['scope'], cases=summaries,
            source_bounds=data['initialization']['source_bounds'], national_acceptance=False,
            all_cases_executed=True, exact_v10_control_ledger_equal=True,
            new_fitted_parameters=0, new_training_executions=0, all_cases_retained_no_ranking=True,
            material_account_rows=len(material), fossil_balance_rows=len(carriers),
            actual_material_emissions_t=None, removal_credit_t=0.,
            interpretation='Retrospective cross-source partition hypothesis. All 27 material GDP responses retained without fitting or selection. No GCB target comparisons for split cases; no national net emissions, storage or avoided-emissions claim.'))
        paths = [Path(__file__), ROOT / 'scripts/build_q2_nonenergy_episode.py',
                 ROOT / 'scripts/prepare_q2_apec_balance.py', ROOT / 'scripts/run_q2_historical_candidate.py',
                 *sorted((ROOT / 'src/energy_model/q2').glob('*.py'))]
        dump(out / 'run_manifest.json', dict(status='material_episode_executed',
            manifest_path=manifest_path.relative_to(ROOT).as_posix(), manifest_sha256=sha(manifest_path),
            parent_ledger_path=PARENT_RESULT, parent_ledger_sha256=sha(ROOT / PARENT_RESULT),
            code_hashes={p.relative_to(ROOT).as_posix(): sha(p) for p in paths},
            outputs={p.name: sha(p) for p in sorted(out.iterdir()) if p.name != 'attempt.json'},
            national_acceptance=False))
        dump(out / 'attempt.json', dict(status='material_episode_executed', national_acceptance=False))
        print('29 trajectories reconciled; exact v10 control; no fitting, selection or national carbon claim')
        return 0
    except Exception as exc:
        dump(out / 'attempt.json', dict(status='failed', reason=str(exc), national_acceptance=False))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    raise SystemExit(execute(parser.parse_args().output_dir))
