"""Offline source-row inventory; never silently resolve plant/unit collisions."""
import argparse
from collections import Counter
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from prepare_q2_nuclear_capacity import reviewed, ROOT
from energy_model.q2.io import csvout, dump, local_path, sha


def source_date(cell):
    if cell is None or cell in ('—', '——'):
        return None
    if not isinstance(cell, str) or len(cell.split('/')) != 3:
        raise ValueError('Invalid original date cell')
    try:
        return date(*map(int, cell.split('/')))
    except (ValueError, TypeError) as exc:
        raise ValueError('Invalid calendar date') from exc


def reconcile(transcription, nbs):
    expected = dict(reference_date='2024-12-31', publication_date='2025-01-07',
                    geography='mainland_China_excludes_Taiwan', capacity_unit='10^4 kW',
                    capacity_basis='rated_power;gross_or_net_not_stated_in_table')
    if any(transcription.get(k) != v for k, v in expected.items()):
        raise ValueError('Unreviewed current-state reference boundary')
    if (nbs['year'], nbs['region'], nbs['variable'], nbs['unit'], nbs['edition']) != (
            '2024', 'China_mainland', 'nuclear_10kW', '10^4 kW', 'NBS_2025'):
        raise ValueError('NBS comparison boundary mismatch')
    cutoff = date.fromisoformat(transcription['reference_date'])
    published = date.fromisoformat(transcription['publication_date'])
    raw = transcription['rows']
    body = transcription['source_body']
    identities = [(r['table'], r['row']) for r in raw]
    if len(set(identities)) != len(raw):
        raise ValueError('Duplicate source table/row')
    labels = Counter((r['plant_cell'], r['unit_cell'], r['technology_cell']) for r in raw)
    short_labels = Counter((r['plant_cell'], r['unit_cell']) for r in raw)
    rows, totals = [], {t: Decimal(0) for t in ('operating', 'construction')}
    for r in raw:
        table = r['table']
        if table not in totals or type(r['row']) is not int or r['row'] < 1:
            raise ValueError('Unknown source table or row')
        try:
            capacity = Decimal(r['rated_capacity_cell'])
        except (InvalidOperation, TypeError) as exc:
            raise ValueError('Invalid rated capacity cell') from exc
        if not capacity.is_finite() or capacity <= 0:
            raise ValueError('Positive finite rated capacity required')
        start = source_date(r['construction_start_cell'])
        grid = source_date(r['first_grid_cell'])
        commercial = source_date(r['commercial_operation_cell'])
        if start is not None and start > cutoff:
            raise ValueError('Construction starts after reference state')
        if grid is not None and (grid > cutoff or (start is not None and grid < start)):
            raise ValueError('First grid date inconsistent with reference state')
        if commercial is not None and (commercial > published or
                (grid is not None and commercial < grid) or (start is not None and commercial < start)):
            raise ValueError('Commercial date inconsistent with published evidence')
        if table == 'construction' and (r['first_grid_cell'] is not None or r['commercial_operation_cell'] is not None):
            raise ValueError('Construction table has no commissioning columns; dates must not be manufactured')
        label = (r['plant_cell'], r['unit_cell'], r['technology_cell'])
        status = ('ambiguous_duplicate_source_label' if labels[label] > 1 else
                  'technology_context_required' if short_labels[label[:2]] > 1 else 'unique_within_source_tables')
        rows.append(dict(source_row_id=f'{table}:{r["row"]:02d}', **r,
            rated_capacity_MW=float(capacity * 10), reference_date=cutoff.isoformat(),
            publication_date=published.isoformat(), source_status_at_cutoff=table,
            construction_start_date=start.isoformat() if start else None,
            first_grid_date=grid.isoformat() if grid else None,
            commercial_operation_date=commercial.isoformat() if commercial else None,
            commercial_status_at_cutoff=('not_a_source_column' if table == 'construction' else
                'date_missing' if commercial is None else 'after_cutoff' if commercial > cutoff else 'reported_by_cutoff'),
            identity_status=status, national_asset_identity_admitted=False,
            permit_valid_through=None, retirement_date=None,
            future_commissioning_date=None, remaining_construction_cost=None,
            capacity_basis=transcription['capacity_basis'],
            source_locator=f'Table {1 if table == "operating" else 2}; printed row {r["row"]}'))
        totals[table] += capacity
    diagnostics = []
    for table in totals:
        group = [r for r in rows if r['table'] == table]
        if sorted(r['row'] for r in group) != list(range(1, body[table + '_count'] + 1)):
            raise ValueError('Missing or unexpected source table row')
        printed = Decimal(body[table + '_capacity'])
        # Explicit diagnostic assumption: the body total is rounded to its
        # last printed decimal. It does not justify any NBS boundary splice.
        tolerance = Decimal(5).scaleb(printed.as_tuple().exponent - 1)
        difference = totals[table] - printed
        if abs(difference) > tolerance:
            raise ValueError('Source table total differs beyond printed rounding')
        diagnostics.append(dict(check=table + '_table_vs_body', value=float(totals[table]),
            reference=float(printed), difference=float(difference), unit='10^4 kW',
            decision='same_source_arithmetic_within_printed_rounding', detail='Not independent validation'))
    starts = [r for r in rows if r['table'] == 'construction' and (r['construction_start_date'] or '').startswith('2024-')]
    start_capacity = sum(Decimal(r['rated_capacity_cell']) for r in starts)
    if len(starts) != body['construction_starts_2024_count'] or start_capacity != Decimal(body['construction_starts_2024_capacity']):
        raise ValueError('2024 construction-start aggregate differs from body')
    diagnostics.append(dict(check='2024_start_capacity', value=float(start_capacity),
        reference=float(body['construction_starts_2024_capacity']), difference=0., unit='10^4 kW',
        decision='same_source_arithmetic_match', detail=f'{len(starts)} construction rows; not a commissioning schedule'))
    diagnostics.append(dict(check='operating_vs_nbs_2024', value=float(totals['operating']),
        reference=float(nbs['value']), difference=float(totals['operating'] - Decimal(nbs['value'])),
        unit='10^4 kW', decision='unresolved_boundary_and_capacity_difference',
        detail='Do not replace NBS6083 or rescale source units; cause not established'))
    for row in rows:
        if row['identity_status'] != 'unique_within_source_tables':
            diagnostics.append(dict(check='source_identity:' + row['source_row_id'], value=None, reference=None,
                difference=None, unit='label', decision=row['identity_status'],
                detail=' / '.join((row['plant_cell'], row['unit_cell'], row['technology_cell']))))
    checks = dict(reference_date=cutoff.isoformat(), publication_date=published.isoformat(),
        source_rows=len(rows), operating_source_rows=58, construction_source_rows=27,
        rated_operating_MW=float(totals['operating'] * 10),
        rated_under_construction_MW=float(totals['construction'] * 10),
        missing_construction_start_rows=[r['source_row_id'] for r in rows if not r['construction_start_date']],
        missing_operating_first_grid_rows=[r['source_row_id'] for r in rows if r['table'] == 'operating' and not r['first_grid_date']],
        after_cutoff_commercial_rows=[r['source_row_id'] for r in rows if r['commercial_status_at_cutoff'] == 'after_cutoff'],
        identity_ambiguous_rows=[r['source_row_id'] for r in rows if r['identity_status'] == 'ambiguous_duplicate_source_label'],
        identity_context_required_rows=[r['source_row_id'] for r in rows if r['identity_status'] == 'technology_context_required'],
        reported_approved_not_started_count=body['approved_operating_construction_total_count']-58-27,
        approved_not_started_capacity_MW=None,
        approved_not_started_note='17 is a difference of reported counts; the rounded1.13e8kW total does not identify17project capacities or permissions.',
        national_model_admission=False, historical_models_changed=False,
        remaining=['Resolve source identity and gross/net capacity boundaries before national asset mapping.',
                   'No operating availability, remaining cash, full permits, retirement or future commissioning dates.',
                   'Published after reference cutoff; not a contemporaneously known2024information set.',
                   'Reported2024generation and2025online forecasts in body are not adopted as observations.'])
    return rows, diagnostics, checks


def prepare(root=ROOT, output_relative='data/processed/q2'):
    review_path = 'data/catalog/q2_nuclear_state_2024_review.json'
    review = reviewed(root, review_path, 'scoped_2024_nuclear_state_reference')
    transcription = json.loads((root / 'data/catalog/q2_nuclear_state_2024_transcription.json').read_text(encoding='utf-8'))
    with (root / 'data/processed/unified/nbs_history.csv').open(encoding='utf-8-sig', newline='') as f:
        matching = [r for r in csv.DictReader(f) if r['year'] == '2024' and r['variable'] == 'nuclear_10kW']
    if len(matching) != 1:
        raise ValueError('Unique NBS comparison required')
    rows, diagnostics, checks = reconcile(transcription, matching[0])
    records = {r['id']: r for r in json.loads((root / 'data/catalog/q2_sources.json').read_text(encoding='utf-8'))}
    for row in rows:
        source_id = review['roles'][row['table']]
        if source_id not in {r['id'] for r in review['source_records']}:
            raise ValueError('Unreviewed table source role')
        row.update(source_id=source_id, source_path=records[source_id]['path'], source_sha256=records[source_id]['sha256'])
    out = local_path(root, output_relative)
    out.mkdir(parents=True, exist_ok=True)
    csvout(out / 'nuclear_state_2024_reference.csv', rows)
    csvout(out / 'nuclear_state_2024_diagnostics.csv', diagnostics)
    checks['review_sha256'] = sha(root / review_path)
    dump(out / 'nuclear_state_2024_checks.json', checks)
    return checks


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', default='data/processed/q2')
    print(json.dumps(prepare(output_relative=parser.parse_args().output_dir), ensure_ascii=False, indent=2))
