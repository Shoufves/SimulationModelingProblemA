"""Offline APEC detailed balance with explicit symbols, hierarchies and units.

The retained 2014 snapshot is a retrospective accounting reference, not evidence
available to 2014 agents or admission of a national service/equipment state.
"""
import csv
import io
import json
import re
import sys
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from energy_model.q2.io import csvout, dump, local_path, sha, verify_source_records

KTOE_TO_PJ = Decimal('0.041868')
TOP_COLUMNS = (1, 7, 15, 16, 17, 18, 24, 42, 46, 47, 48, 49, 51, 52, 53, 59, 69, 70)


class HTMLTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.row = []
        if tag in ('td', 'th'): self.cell = []

    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            if self.row is None: raise ValueError('HTML cell outside table row')
            self.row.append(' '.join(''.join(self.cell).split()))
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def value(token):
    if token == '-': return None
    if not re.fullmatch(r'-?\d+', token):
        raise ValueError('Unreviewed APEC numeric token: ' + repr(token))
    return Decimal(token)


def parse_table(text, caption, review):
    rows = list(csv.reader(io.StringIO(text), delimiter='\t'))
    if rows[:2] != [['Energy Balance Table'], ['China', '2014', caption]]:
        raise ValueError('APEC geography, year or unit caption changed')
    table = rows[2:]
    if len(table) != 96 or any(len(r) != 73 for r in table):
        raise ValueError('APEC detailed table dimensions changed')
    if table[0] != review['column_labels'] or [r[0] for r in table] != review['row_labels']:
        raise ValueError('APEC row/column labels changed')
    for row in table[1:]:
        for token in row[1:]: value(token)
    return table


def row_unit(index, caption_unit):
    return 'GWh' if index == 94 else 'ktoe' if index == 95 else caption_unit


def column_role(col):
    if col == 71: return 'total_control'
    if col == 72: return 'renewables_memo_subset'
    if col == 50: return 'pv_memo_subset_of_solar'
    return 'top_level_product' if col in TOP_COLUMNS else 'product_detail'


def crosscheck_units(ktoe, pj):
    checks = []
    for r in range(1, 96):
        for c in range(1, 73):
            left, right = value(ktoe[r][c]), value(pj[r][c])
            if (left is None) != (right is None):
                raise ValueError(f'APEC missing symbol differs between exports at {r},{c}')
            if left is None: continue
            factor = Decimal(1) if r >= 94 else KTOE_TO_PJ
            bound = Decimal(0) if r >= 94 else (Decimal(1) + factor) / 2
            residual = left * factor - right
            if abs(residual) > bound:
                raise ValueError(f'APEC cross-unit discrepancy at {r},{c}')
            checks.append({'row': r, 'column': c, 'residual': float(residual),
                           'rounding_bound': float(bound), 'passed': True})
    return checks


def check_identity(table, name, total, terms):
    tokens = [table[r][c] for r, c in [total, *terms]]
    vals = [value(t) for t in tokens]
    missing = [list(cell) for cell, v in zip([total, *terms], vals) if v is None]
    if missing:
        return {'identity': name, 'total_cell': total, 'term_cells': terms,
                'status': 'not_testable_unresolved_symbol', 'missing_cells': missing,
                'residual': None, 'rounding_bound': None}
    residual = sum(vals[1:], Decimal(0)) - vals[0]
    bound = Decimal('.5') * len(vals)
    if abs(residual) > bound:
        raise ValueError('APEC accounting identity exceeds printed rounding: ' + name)
    return {'identity': name, 'total_cell': total, 'term_cells': terms,
            'status': 'passed_within_printed_rounding', 'missing_cells': [],
            'residual': float(residual), 'rounding_bound': float(bound)}


def accounting_checks(table):
    specs = [('supply_signed', 7, [1, 2, 3, 4, 5, 6]),
             ('supply_to_final_with_discrepancy', 60, [7, 8, 13, 39, 59]),
             ('energy_and_nonenergy_final', 60, [61, 89]),
             ('three_final_energy_sectors', 61, [62, 76, 83]),
             ('losses_and_own_use', 39, [40, 58]),
             ('nonenergy_sectors', 89, [90, 91, 92, 93])]
    checks = [check_identity(table, name, (total, c), [(r, c) for r in terms])
              for name, total, terms in specs for c in range(1, 73)]
    checks.extend(check_identity(table, 'top_level_products', (r, 71),
                                 [(r, c) for c in TOP_COLUMNS]) for r in range(1, 94))
    return checks


def extract(table, review):
    out = []
    source = review['ktoe_export']
    for r in range(1, 96):
        unit = row_unit(r, 'ktoe')
        for c in range(1, 73):
            token = table[r][c]
            number = value(token)
            pj = None if number is None else number * (Decimal('.0036') if unit == 'GWh' else KTOE_TO_PJ)
            out.append({'year': 2014, 'geography': 'APEC_China_code_005',
                        'flow': table[r][0], 'product': table[0][c],
                        'value': None if number is None else int(number), 'unit': unit,
                        'value_PJ': None if pj is None else float(pj),
                        'raw_token': token,
                        'status': 'unresolved_dash' if number is None else 'reported_rounded_number',
                        'negative_zero': token == '-0', 'column_role': column_role(c),
                        'row_role': 'output_memo' if r >= 94 else 'balance_flow',
                        'source_tsv_line': r + 3, 'source_column': c + 1,
                        'source_path': source, 'source_sha256': review['ktoe_sha256'],
                        'data_vintage': 'unspecified_database_revision_retrieved_2026-10-19',
                        'conversion': '1 ktoe = 0.041868 PJ; output GWh = 0.0036 PJ; no statistical-gap allocation'})
    return out


def final_energy_bounds(table):
    """Bound missing end-use products without assigning zeros or useful services.

    This inference assumes nonnegative gross final energy, and nearest-integer
    rounding (each printed integer +/-0.5 ktoe). Missing products share ONE
    residual bound; the bound must not be independently assigned to every fuel.
    """
    results = []
    for r in (62, 76, 83):
        total = value(table[r][71])
        values = [(c, value(table[r][c])) for c in TOP_COLUMNS]
        if total is None or total < 0 or any(v is not None and v < 0 for _, v in values):
            raise ValueError('Nonnegative final energy needed for interval bridge')
        known = [(c, v) for c, v in values if v is not None]
        unknown = [c for c, v in values if v is None]
        lower = sum((max(Decimal(0), v-Decimal('.5')) for _, v in known), Decimal(0))
        upper = sum((v+Decimal('.5') for _, v in known), Decimal(0))
        aggregate_lower = max(Decimal(0), total-Decimal('.5')-upper)
        aggregate_upper = total+Decimal('.5')-lower
        if aggregate_upper < 0 or (not unknown and aggregate_lower > 0):
            raise ValueError('No feasible nonnegative missing-product balance')
        if not unknown: aggregate_upper = Decimal(0)
        for c, number in values:
            results.append({'year':2014, 'sector':table[r][0], 'product':table[0][c],
                'source_tsv_line':r+3, 'source_column':c+1, 'unit':'ktoe',
                'reported_value':None if number is None else int(number),
                'individual_lower':0. if number is None else float(max(Decimal(0),number-Decimal('.5'))),
                'individual_upper':float(aggregate_upper if number is None else number+Decimal('.5')),
                'status':'bounded_unassigned_missing' if number is None else 'reported_rounded_final_energy',
                'missing_group':f'row{r}_all_dash_top_products' if number is None else '',
                'missing_group_sum_lower':float(aggregate_lower),
                'missing_group_sum_upper':float(aggregate_upper),
                'missing_group_size':len(unknown), 'sector_total_ktoe':int(total),
                'known_sum_ktoe':int(sum((v for _,v in known),Decimal(0))),
                'service_definition':'carrier energy consumed; not useful heat/passenger-km or equipment',
                'assumptions':'Nonnegative gross final energy; each integer rounded to nearest1ktoe. All missing cells jointly share group bound; none filled zero.'})
    return results


def prepare(root=ROOT, output_dir=None):
    review_path = root/'data/catalog/q2_apec_balance_review.json'
    review = json.loads(review_path.read_text(encoding='utf-8'))
    if review['decision'] != 'scoped_retrospective_energy_accounting_reference':
        raise ValueError('APEC use not admitted')
    if not review['checks'] or not all(c['passed'] and c['evidence'] for c in review['checks']):
        raise ValueError('APEC substantive review missing')
    for record in review['fingerprints']:
        if sha(local_path(root, record['path'])) != record['sha256']:
            raise ValueError('APEC source changed: ' + record['path'])
    verify_source_records(root, review['source_records'])
    tables = []
    for unit, caption in [('ktoe', 'Unit:KTOE'), ('pj', 'Unit:Peta Joule')]:
        table = parse_table(local_path(root, review[unit+'_export']).read_text(encoding='utf-8'), caption, review)
        html = HTMLTable()
        html.feed(local_path(root, review[unit+'_html']).read_text(encoding='utf-8'))
        if table != html.rows: raise ValueError('APEC HTML/TSV mismatch')
        tables.append(table)
    unit_checks = crosscheck_units(*tables)
    checks = accounting_checks(tables[0])
    rows = extract(tables[0], review)
    sector_bounds = final_energy_bounds(tables[0])
    out = Path(output_dir) if output_dir else root/'data/processed/q2'
    out.mkdir(parents=True, exist_ok=True)
    csvout(out/'apec_balance_2014.csv', rows)
    csvout(out/'apec_balance_2014_identities.csv', checks)
    csvout(out/'apec_balance_2014_sector_bounds.csv', sector_bounds)
    # Sector controls are direct source values, never a sum of parents and children.
    controls = [r for r in rows if r['source_tsv_line'] - 3 in (7, 8, 13, 39, 59, 60, 61, 62, 76, 83, 89, 94, 95)
                and r['column_role'] == 'total_control']
    csvout(out/'apec_balance_2014_controls.csv', controls)
    summary = {'decision': review['decision'], 'rows': len(rows),
               'unresolved_dash_count': sum(r['value'] is None for r in rows),
               'negative_zero_count': sum(r['negative_zero'] for r in rows),
               'html_tsv_exact_agreement': True, 'same_source_unit_checks': len(unit_checks),
               'maximum_cross_unit_residual_PJ': max(abs(c['residual']) for c in unit_checks if c['row'] < 94),
               'identities_passed': sum(c['status'].startswith('passed') for c in checks),
               'identities_not_testable': sum(c['status'].startswith('not_testable') for c in checks),
               'national_initialization_admitted': False,
               'review_sha256': sha(review_path),
               'outputs': {p.name: sha(p) for p in sorted(out.glob('apec_balance_2014*.csv'))}}
    dump(out/'apec_balance_2014_checks.json', summary)
    return summary


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(output_dir=args.output_dir), ensure_ascii=False))
