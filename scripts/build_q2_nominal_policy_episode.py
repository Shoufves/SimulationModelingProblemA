"""Freeze a limited 2015 PV application-cohort episode; no parameter fitting.

Three actual 2013 zone benchmarks are separate conditional assignments, never
national weights. Compare annual nominal conversion with a fixed-real quote at
the 2015 factor, using the same v9 training-selected model and inherited funds.
"""
from copy import deepcopy
import csv
import json
from pathlib import Path

import run_q2_historical_candidate as history
from energy_model.q2.io import dump, local_path, sha, verify_source_records

ROOT = history.ROOT
REVIEW = 'data/catalog/q2_nominal_policy_episode_review.json'
DIRECTORY = 'workflow/q2_candidates/nominal_policy_episode'


def references():
    review = json.loads((ROOT / REVIEW).read_text(encoding='utf-8'))
    if (review['decision'] != 'limited_nominal_policy_episode_research' or not review['checks'] or
            not all(c['passed'] is True and c['evidence'] for c in review['checks'])):
        raise ValueError('Limited policy-episode mapping not reviewed')
    for item in review['fingerprints']:
        if sha(local_path(ROOT, item['path'])) != item['sha256']:
            raise ValueError('Policy episode reference changed: ' + item['path'])
    verify_source_records(ROOT, review['source_records'])
    return review


def build():
    review = references()
    _, parent = history.load_frozen(ROOT / 'workflow/q2_candidates/v9/manifest.json')
    selected = json.loads((ROOT / 'outputs/q2/historical_candidate_v9/training_selection.json').read_text(encoding='utf-8'))['selected']
    base = history.parameterize(history.rule_model(parent['structural_models'][selected['structure']], selected['rule']),
                                parent['experiment']['parameters'], selected['parameters'])
    def rows(path):
        with (ROOT / path).open(encoding='utf-8-sig', newline='') as stream:
            return list(csv.DictReader(stream))
    prices = {r['zone']: r for r in rows('data/processed/q2/policy_reference.csv') if r['technology'] == 'utility_pv'}
    conversion = {int(r['year']): float(r['million_USD2008_per_CNY_nominal'])
                  for r in rows('data/processed/q2/currency_bridge_2008_2024.csv')}
    if set(prices) != {'I', 'II', 'III'} or not set(range(2014, 2025)) <= set(conversion):
        raise ValueError('Incomplete reviewed policy zones or annual currency factors')
    models = {'v9_control': deepcopy(base)}
    cases = [dict(id='v9_control', quote_mode='no_episode_contract', zone=None)]
    inherited_cash = next(a['cash'] for a in base['agents'] if a['role'] == 'government')
    for zone in ('I', 'II', 'III'):
        price = prices[zone]
        if price['payment_kind'] != 'total_benchmark_tariff_not_additional_premium' or int(price['support_years']) != 20:
            raise ValueError('Unexpected tariff kind or support duration')
        nominal_quote = float(price['price_CNY_nominal_per_MWh'])
        for mode in ('nominal', 'fixed_real_2015'):
            name = f'{mode}_zone_{zone}'
            model = deepcopy(base)
            model['model_currency'] = 'million_USD_2008'
            option = next(o for o in model['investment_options'] if o['id'] == 'solar_new_build')
            if option['lead_years'] != 1:
                raise ValueError('Episode annual commissioning assumption requires one model step')
            quote = nominal_quote if mode == 'nominal' else nominal_quote * conversion[2015]
            option['revenue_contract'] = dict(id='conditional_2015_pv_' + zone, known_year=2015,
                application_from_year=2015, application_through_year=2015, commission_by_year=2016,
                support_years=20, output_carrier='electricity_bus', price_mode='fixed_total_price',
                price_per_mwh=quote, payer='government', source_or_assumption=REVIEW + '#' + name)
            if mode == 'nominal':
                option['revenue_contract']['nominal_currency'] = 'CNY_nominal'
            template = deepcopy(base['policies'][0])
            model['policies'] = []
            for year in range(base['start_year'], base['end_year'] + 1):
                policy = deepcopy(template)
                policy.update(id=f'episode_visible_{year}', known_year=year, effective_year=year,
                              operating_support_budget=inherited_cash)
                if mode == 'nominal':
                    policy['currency_conversions'] = {'CNY_nominal': dict(
                        factor=conversion[year], model_currency='million_USD_2008', conversion_year=year,
                        known_year=year, source_or_assumption=REVIEW + '#retrospective_year_end_conversion')}
                model['policies'].append(policy)
            models[name] = model
            cases.append(dict(id=name, quote_mode=mode, zone=zone, policy_record=price['id'],
                              nominal_CNY_per_MWh=nominal_quote, fixed_quote_if_used=quote,
                              inherited_annual_support_ceiling=inherited_cash))
    return dict(model=deepcopy(base), structural_models=models, definitions=parent['definitions'],
        observations=parent['observations'], acceptance=parent['acceptance'],
        experiment=dict(targets=parent['experiment']['targets'], windows=parent['experiment']['windows'],
                        selection='No fitting or selection in this episode; retain every predeclared case.'),
        initialization=dict(parent_training_selection=selected, currency='million_USD_2008',
                            opening_state_and_cash_unchanged=True),
        episode=dict(scope='limited_2015_pv_policy_episode_not_national_history', cases=cases,
                     source_review=REVIEW, assumptions=review['mapping_assumptions'], national_acceptance=False))


def freeze():
    data = build()
    review = references()
    parent = json.loads((ROOT / 'workflow/q2_candidates/v9/manifest.json').read_text(encoding='utf-8'))
    artifacts = dict(parent['source_artifacts'])
    artifacts.update({item['path']: item['sha256'] for item in review['fingerprints']})
    artifacts[REVIEW] = sha(ROOT / REVIEW)
    directory = ROOT / DIRECTORY
    if directory.exists():
        for name, document in data.items():
            if json.loads((directory / (name + '.json')).read_text(encoding='utf-8')) != document:
                raise ValueError('Frozen nominal policy episode changed; use a new version')
        if json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))['source_artifacts'] != artifacts:
            raise ValueError('Frozen episode source binding changed')
        return 'Existing seven-case episode reproduced exactly'
    directory.mkdir(parents=True)
    for name, document in data.items():
        dump(directory / (name + '.json'), document)
    dump(directory / 'manifest.json', dict(version=1, study_kind='fixed_policy_episode_no_calibration',
        scope=parent['scope'], national_admission=False, frozen_before_first_run=True,
        builder_sha256=sha(Path(__file__)),
        inputs={name: dict(path=(directory / (name + '.json')).relative_to(ROOT).as_posix(),
                          sha256=sha(directory / (name + '.json'))) for name in data},
        source_artifacts=artifacts,
        admission_limitation='One hypothetical eligible application cohort under actual zone prices; no zone weights, full policy calendar, national fiscal data or national calibration.'))
    return 'Frozen seven-case policy episode; no new fitted parameters or selected policy zone'


if __name__ == '__main__':
    print(freeze())
