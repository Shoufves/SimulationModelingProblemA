"""Reproduce the reviewed 2015 nuclear permit/capacity/start crosswalk offline.

The PDF cells were visually transcribed; this entry verifies their pinned review
and joins by plant/unit, never by the conflicting source-local CN codes. It does
not produce an executable model calendar or infer dates from missing cells.
"""
import argparse
from datetime import date
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from energy_model.q2.io import csvout, dump, local_path, sha, verify_source_records


def reviewed(root, path, decision):
    review = json.loads(local_path(root, path).read_text(encoding='utf-8'))
    if (review['decision'] != decision or not review['checks'] or
            not all(c['passed'] is True and c['evidence'] for c in review['checks'])):
        raise ValueError('Nuclear reference review unresolved: '+path)
    if not review['fingerprints']:
        raise ValueError('Nuclear reference requires fingerprints')
    for item in review['fingerprints']:
        if sha(local_path(root, item['path'])) != item['sha256']:
            raise ValueError('Nuclear reference changed: '+item['path'])
    verify_source_records(root, review['source_records'])
    return review


def reconcile(transcription, permits):
    """Semantic join kept separate so counterexamples can exercise it directly."""
    if (transcription['reference_date'] != '2015-12-31' or
            transcription['report_date'] != '2016-06' or
            transcription['capacity_unit'] != 'MW(e)' or
            transcription['gross_or_net_basis'] != 'not_specified'):
        raise ValueError('Unreviewed nuclear time or capacity boundary')
    cutoff = date.fromisoformat(transcription['reference_date'])
    records = {}
    for p in permits['records']:
        for unit in p['units']:
            key = (p['plant'], unit)
            if key in records:
                raise ValueError('Duplicate permit plant/unit')
            records[key] = p
    rows, conflicts, identities, joined = [], [], set(), set()
    for r in transcription['observations']:
        key = (r['plant'], r['unit'])
        if key not in records or key in joined or r['id'] in identities:
            raise ValueError('Unmatched or duplicate nuclear plant/unit')
        p = records[key]
        if r['permit_record_id'] != p['id'] or r['construction_permit_date'] != p['approval_date']:
            raise ValueError('Permit date or identity differs from reviewed original')
        issued = date.fromisoformat(r['construction_permit_date'])
        if issued.year != 2015 or issued > cutoff:
            raise ValueError('Permit outside reviewed year')
        value = r['capacity_MWe']
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('Invalid electric capacity')
        start = r['construction_start_date']
        if start is None:
            if r['construction_cell'] != '已核准':
                raise ValueError('Missing start must retain original non-date status')
        elif r['construction_cell'] != start or not issued <= date.fromisoformat(start) <= cutoff:
            raise ValueError('Start date inconsistent with original status or permit')
        if any(r[k] is not None for k in ('first_grid_date', 'commercial_operation_date', 'operating_permission_date')):
            raise ValueError('Unreviewed commissioning or operating permission')
        release = r['first_concrete_release_date']
        evidence = r['first_concrete_release_evidence']
        if evidence == 'approved_in_notice':
            if release is None or not issued <= date.fromisoformat(release) <= cutoff:
                raise ValueError('Approved release needs a valid dated notice')
            if start is not None and date.fromisoformat(release) > date.fromisoformat(start):
                raise ValueError('Release after reported first construction')
        elif evidence in ('not_reviewed', 'separate_release_required_not_found'):
            if release is not None:
                raise ValueError('Missing release evidence cannot create a date')
        else:
            raise ValueError('Unknown release evidence state')
        # No release is inferred from a subsequently reported start date.
        code = r['original_permit_code']
        if code is not None and code != r['cns_code']:
            collisions = [x['id'] for x in transcription['observations'] if x['cns_code'] == code]
            conflicts.append(dict(id=r['id'], field='source_local_CN_code',
                                  original_permit_code=code, cns_code=r['cns_code'],
                                  wrong_CNS_join_ids=collisions,
                                  disposition='unresolved_code_disagreement; join_by_reviewed_plant_and_unit'))
        row = dict(r, reference_date=transcription['reference_date'],
                   report_date=transcription['report_date'],
                   report_publication_date=transcription['report_publication_date'],
                   capacity_unit=transcription['capacity_unit'],
                   gross_or_net_basis=transcription['gross_or_net_basis'],
                   capacity_source_id=transcription['source_id'],
                   admission='retrospective_reference_only_not_model_calendar')
        rows.append(row)
        identities.add(r['id'])
        joined.add(key)
    if joined != set(records) or len(rows) != permits['reported_year_total_units']:
        raise ValueError('Not all reviewed licensed units have capacity/status references')
    checks = dict(scope='retrospective_2015_nuclear_reference', units=len(rows),
                  capacity_MWe=sum(r['capacity_MWe'] for r in rows),
                  start_date_reported_units=sum(r['construction_start_date'] is not None for r in rows),
                  approved_without_start_date_units=sum(r['construction_start_date'] is None for r in rows),
                  source_code_conflicts=len(conflicts),
                  construction_first_concrete_operation_separated=True,
                  prior_permit_unit_count_reconciled=True,
                  full_year_calendar_complete=False, national_model_admission=False)
    return rows, conflicts, checks


def prepare(root=ROOT, output_dir=None):
    root = Path(root)
    review_path = 'data/catalog/q2_nuclear_capacity_2015_review.json'
    review = reviewed(root, review_path, 'scoped_2015_nuclear_capacity_start_reference')
    permits = reviewed(root, review['parent_review'], 'scoped_2015_construction_permit_identity_count_reconciled')
    path = root/'data/catalog/q2_nuclear_capacity_2015_transcription.json'
    transcription = json.loads(path.read_text(encoding='utf-8'))
    rows, conflicts, checks = reconcile(transcription, permits)
    checks['review_sha256'] = sha(root/review_path)
    checks['transcription_sha256'] = sha(path)
    checks['sources'] = [{k:r[k] for k in ('path','sha256')} for r in review['fingerprints']]
    out = Path(output_dir) if output_dir is not None else root/'data/processed/q2'
    out.mkdir(parents=True, exist_ok=True)
    csvout(out/'nuclear_capacity_2015_reference.csv', rows)
    csvout(out/'nuclear_capacity_2015_conflicts.csv', conflicts)
    dump(out/'nuclear_capacity_2015_checks.json', checks)
    return checks


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(output_dir=args.output_dir), ensure_ascii=False, indent=2))
