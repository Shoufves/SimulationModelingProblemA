"""Reproduce reported transport activity without inferring fuel consumption."""
import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from energy_model.q2.demand import validate_activity_driver
from energy_model.q2.io import csvout, dump, local_path, sha, verify_source_records

MODES = {'C16-06': ('total','rail','road','water','civil_aviation'),
         'C16-08': ('total','rail','road','water','ocean_subset','civil_aviation','pipeline')}
UNITS = {'C16-06':'10^8 passenger_km', 'C16-08':'10^8 tonne_km'}
BOUNDARIES = {
    'total':'NBS2025_mixed_transport_modes_as_published',
    'rail':'NBS2025_public_rail_excluding_military_and_nonpublic_dedicated_lines',
    'road':'NBS2025_registered_commercial_road_transport_not_private_car_travel',
    'water':'NBS2025_registered_commercial_water_transport',
    'ocean_subset':'NBS2025_ocean_subset_of_water_unbridged_revision',
    'civil_aviation':'NBS2025_domestic_registered_air_carriers_including_international_routes',
    'pipeline':'NBS2025_reported_pipeline_freight_throughput_not_own_energy_consumption'}


def reconcile(transcription):
    if transcription['edition'] != 'NBS_2025' or transcription['years'] != [2014,2024]:
        raise ValueError('Transport edition or window differs from reviewed evidence')
    rows, values = [], {}
    unresolved = {(r['table'],r['mode']) for r in transcription['suspicious_transitions']}
    for raw in transcription['observations']:
        table,year,mode = raw['table'],raw['year'],raw['mode']
        key = table,year,mode
        if (table not in MODES or type(year) is not int or not 2014<=year<=2024 or
                mode not in MODES[table] or key in values):
            raise ValueError('Duplicate or unreviewed transport identity/year')
        role = 'total_control' if mode=='total' else 'subset_of_water' if mode=='ocean_subset' else 'disjoint_mode'
        if raw['unit'] != UNITS[table] or raw['column_role'] != role:
            raise ValueError('Transport unit or aggregate/subset role changed')
        try:
            value = Decimal(raw['value_cell'])
        except (InvalidOperation,TypeError) as exc:
            raise ValueError('Invalid transport activity cell') from exc
        if not value.is_finite() or value < 0:
            raise ValueError('Nonnegative finite transport activity required')
        values[key] = value
        rows.append(dict(**raw,value=float(value),boundary=BOUNDARIES[mode],
            comparability='unresolved_transition' if (table,mode) in unresolved else 'reported_series_no_bridge_inferred',
            data_vintage='NBS2025_retrospective_revision',
            national_service_or_energy_mapping_admitted=False,
            energy_intensity=None,equipment_fuel_share=None,
            notes='Passenger/freight units remain separate; annual activity is not a fuel demand or a contemporaneous forecast.'))
    expected = {(table,year,mode) for table,modes in MODES.items() for year in range(2014,2025) for mode in modes}
    if set(values) != expected:
        raise ValueError('Transport reference has missing/unexpected cells; no filling permitted')
    diagnostics = []
    for table,modes in MODES.items():
        components = [mode for mode in modes if mode not in ('total','ocean_subset')]
        for year in range(2014,2025):
            total = values[table,year,'total']
            subtotal = sum(values[table,year,mode] for mode in components)
            tolerance = sum(Decimal(5).scaleb(values[table,year,mode].as_tuple().exponent-1)
                            for mode in ['total',*components])
            residual = total-subtotal
            diagnostics.append(dict(table=table,year=year,total=float(total),disjoint_mode_sum=float(subtotal),
                residual=float(residual),rounding_diagnostic_bound=float(tolerance),unit=UNITS[table],
                passed=abs(residual)<=tolerance,
                interpretation='Sum excludes ocean subset; nearest-printed-unit rounding is an explicit diagnostic assumption, not a data adjustment.'))
            if table=='C16-08' and values[table,year,'ocean_subset']>values[table,year,'water']:
                raise ValueError('Ocean subset exceeds reported water total')
    return rows,diagnostics


def activity_series(rows, table, mode):
    if mode in ('total','ocean_subset'):
        raise ValueError('Use a distinct service, not a mixed-mode total or overlapping subset')
    selected = sorted([r for r in rows if r['table']==table and r['mode']==mode],key=lambda r:r['year'])
    if not selected or any(r['comparability']=='unresolved_transition' for r in selected):
        raise ValueError('Transport activity transition remains unbridged')
    series = dict(id=f'NBS2025_{table}_{mode}',base_year=2014,unit=selected[0]['unit'],boundary=selected[0]['boundary'],
        information_role='realized_current_year_operation_only',
        records=[dict(year=r['year'],value=r['value'],unit=r['unit'],boundary=r['boundary'],
            status='retrospective_observation',source_or_assumption=r['source_id']+'; '+r['locator']) for r in selected],
        mapping_limit='Activity reference only. No fuel intensity, equipment efficiency,private mobility or territorial energy equivalence is implied.')
    validate_activity_driver(dict(activity_series=series),2014,2024)
    return series


def prepare(root=ROOT, output_relative='data/processed/q2'):
    path = root/'data/catalog/q2_transport_activity_review.json'
    review = json.loads(path.read_text(encoding='utf-8'))
    if (review['decision']!='scoped_transport_activity_reference' or not review['checks'] or
            not all(r['passed'] is True and r['evidence'] for r in review['checks'])):
        raise ValueError('Transport activity review unresolved')
    for item in review['fingerprints']:
        if sha(local_path(root,item['path'])) != item['sha256']:
            raise ValueError('Transport transcription or reference changed')
    verify_source_records(root,review['source_records'])
    transcription=json.loads((root/'data/catalog/q2_transport_activity_transcription.json').read_text(encoding='utf-8'))
    rows,diagnostics=reconcile(transcription)
    if not all(r['passed'] for r in diagnostics):
        failed = [(r['table'], r['year'], r['residual']) for r in diagnostics if not r['passed']]
        raise ValueError(f'Transport arithmetic unresolved; no activity series exported: {failed}')
    sources={r['id']:r for r in json.loads((root/'data/catalog/q2_sources.json').read_text(encoding='utf-8'))}
    for row in rows:
        identifier=review['roles']['passenger' if row['table']=='C16-06' else 'freight']
        if identifier not in {r['id'] for r in review['source_records']}:
            raise ValueError('Unreviewed transport table role')
        row.update(source_id=identifier,source_path=sources[identifier]['path'],source_sha256=sources[identifier]['sha256'])
    usable,withheld={},[]
    for table,modes in MODES.items():
        for mode in modes:
            name=f'{table}:{mode}'
            try:usable[name]=activity_series(rows,table,mode)
            except ValueError as exc:withheld.append(dict(series=name,reason=str(exc)))
    checks=dict(source_cells=len(rows),arithmetic_checks=len(diagnostics),
        arithmetic_passed=all(r['passed'] for r in diagnostics),
        exported_activity_series=list(usable),withheld=withheld,
        unresolved_transitions=transcription['suspicious_transitions'],
        source_review_sha256=sha(path),national_model_admission=False,
        model_energy_intensities_or_future_paths_supplied=False,scope_notes=transcription['scope_notes'])
    out=local_path(root,output_relative);out.mkdir(parents=True,exist_ok=True)
    csvout(out/'transport_activity_2014_2024.csv',rows)
    csvout(out/'transport_activity_arithmetic.csv',diagnostics)
    dump(out/'transport_activity_series.json',usable)
    dump(out/'transport_activity_checks.json',checks)
    return checks


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',default='data/processed/q2')
    print(json.dumps(prepare(output_relative=parser.parse_args().output_dir),ensure_ascii=False,indent=2))
