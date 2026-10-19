"""Offline policy-vintage reference, preserving announced and withdrawn tariffs.

Visibility follows the verified website publication date. This is a conservative
information cutoff, not proof of the earliest public availability. Project-level
eligibility, geography, currency conversion and national weights remain separate.
"""
import argparse
from copy import deepcopy
from datetime import date
import json
from math import isfinite
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from energy_model.q2.io import csvout, dump, local_path, sha, verify_source_records


def validate(document):
    schedules = document['schedules']
    if not schedules or len({s['id'] for s in schedules}) != len(schedules):
        raise ValueError('Empty or duplicated policy schedules')
    lookup = {s['id']: s for s in schedules}
    for schedule in schedules:
        issued = date.fromisoformat(schedule['issued_date'])
        published = date.fromisoformat(schedule['web_publication_date'])
        date.fromisoformat(schedule['nominal_cohort_start'])
        if issued > published or schedule['information_date_basis'] != 'verified_web_publication_conservative_cutoff':
            raise ValueError('Invalid policy information chronology')
        if not schedule['eligibility'] or not schedule['source_ids'] or not schedule['source_locator']:
            raise ValueError('Missing policy eligibility or evidence')
        prices = schedule['prices']
        if not prices or len({p['zone'] for p in prices}) != len(prices):
            raise ValueError('Empty or duplicated tariff zones')
        for price in prices:
            value = price['CNY_nominal_per_kWh']
            if type(value) not in (int, float) or not isfinite(value) or value <= 0 or not price['region_description']:
                raise ValueError('Invalid tariff or absent geography')
        if schedule['payment_kind'] != 'total_benchmark_tariff_not_additional_premium':
            raise ValueError('Reference contains an unreviewed payment kind')
        replacement = schedule['superseded_by']
        if replacement is not None:
            if replacement not in lookup or replacement == schedule['id']:
                raise ValueError('Missing or self-referential policy replacement')
            new = lookup[replacement]
            if (new['technology'] != schedule['technology'] or
                    date.fromisoformat(new['web_publication_date']) <= published or
                    new['nominal_cohort_start'] != schedule['nominal_cohort_start']):
                raise ValueError('Replacement must be a later notice for the same nominal cohort')
            if not schedule['supersession_evidence']:
                raise ValueError('Cancellation needs an explicit original statement')
    return schedules


def visible_schedules(document, as_of):
    """Known notices, including future announced schedules; never contract awards.

Only an explicit withdrawal removes a schedule, and only once its replacement
is public. Older grandfathered schedules are not erased by a newer tariff.
"""
    cutoff = date.fromisoformat(as_of)
    schedules = validate(document)
    lookup = {s['id']: s for s in schedules}
    visible = []
    for schedule in schedules:
        if date.fromisoformat(schedule['web_publication_date']) > cutoff:
            continue
        replacement = schedule['superseded_by']
        if replacement is not None and date.fromisoformat(lookup[replacement]['web_publication_date']) <= cutoff:
            continue
        visible.append(deepcopy(schedule))
    return visible


def load_reviewed(root):
    review = json.loads((root / 'data/catalog/q2_policy_timeline_review.json').read_text(encoding='utf-8'))
    if (review['decision'] != 'scoped_policy_vintage_reference' or not review['fingerprints'] or not review['checks'] or
            not all(c['passed'] is True and c['evidence'] for c in review['checks'])):
        raise ValueError('Policy timeline not substantively reviewed')
    for item in review['fingerprints']:
        if sha(local_path(root, item['path'])) != item['sha256']:
            raise ValueError('Policy timeline fingerprint mismatch: ' + item['path'])
    verify_source_records(root, review['source_records'])
    document = json.loads((root / 'data/catalog/q2_policy_timeline_transcription.json').read_text(encoding='utf-8'))
    schedules = validate(document)
    bound = {r['id'] for r in review['source_records']}
    if any(not set(s['source_ids']) <= bound for s in schedules):
        raise ValueError('Unreviewed policy source')
    return review, document


def prepare(root=ROOT, output_relative='data/processed/q2'):
    review, document = load_reviewed(root)
    rows, events = [], []
    lookup = {s['id']: s for s in document['schedules']}
    for schedule in document['schedules']:
        replacement = lookup.get(schedule['superseded_by'])
        for price in schedule['prices']:
            rows.append({**{k: v for k, v in schedule.items() if k != 'prices'}, **price,
                         'CNY_nominal_per_MWh': price['CNY_nominal_per_kWh'] * 1000,
                         'admission': 'scoped_reference_not_national_contract'})
        events.append(dict(schedule_id=schedule['id'], event='notice_visible',
                           date=schedule['web_publication_date'], related_schedule=None))
        if replacement:
            events.append(dict(schedule_id=schedule['id'], event='explicit_supersession_visible',
                               date=replacement['web_publication_date'], related_schedule=replacement['id']))
    out = local_path(root, output_relative)
    out.mkdir(parents=True, exist_ok=True)
    csvout(out / 'policy_timeline_reference.csv', rows)
    csvout(out / 'policy_timeline_events.csv', sorted(events, key=lambda e: (e['date'], e['schedule_id'], e['event'])))
    checks = dict(decision=review['decision'], schedules=len(lookup), prices=len(rows), events=len(events),
                  cancelled_announcements=sum(s['superseded_by'] is not None for s in document['schedules']),
                  review_sha256=sha(root / 'data/catalog/q2_policy_timeline_review.json'),
                  national_model_admission=False, historical_model_changed=False,
                  unresolved=['National zone/cohort weights, VAT and currency/price-year conversion.',
                              'Per-project subsidy-scale admission, construction and commissioning dates.',
                              'Full subsequent policy sequence and fiscal payment timing.',
                              'These notices do not establish complete support durations or measured national prices.'])
    dump(out / 'policy_timeline_checks.json', checks)
    return checks


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', default='data/processed/q2')
    print(json.dumps(prepare(output_relative=parser.parse_args().output_dir), ensure_ascii=False, indent=2))
