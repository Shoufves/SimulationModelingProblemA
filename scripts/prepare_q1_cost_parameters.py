"""Port of the wind-cost extraction in mmj PR #4 baf1975.

Only the existing seven IRENA pages and six parameter rows are used.
Called explicitly by prepare_q1_review.py, never by the offline Q1 runner.
"""
import csv
import hashlib
import re
from pypdf import PdfReader


def prepare(root):
    path = root / 'data/raw/batch3_scenarios/irena_power_costs_2024.pdf'
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != 'ffe8ce4bde29616f3edf9ef1a86dbb6ae2d5381a0ecb9bb1f71bb20204b6bada':
        raise ValueError('IRENA original differs from the accepted mmj source edition')
    reader = PdfReader(path)
    assertions = [
        (71, r'(?m)^China\s+1\s+489\s+1\s+765\s+2\s+066\s+626\s+856\s+1\s+315'),
        (119, r'(?m)^China\s+3\s+307\s+5\s+268\s+5\s+852\s+1\s+434\s+1\s+520\s+1\s+869'),
        (76, r'China\s+25\s+35\s+33'), (123, r'China\s+.*?37'),
        (209, r'China\s+29'), (212, r'China\s+59'), (202, r'Wind power\s+25')]
    checks = []
    for page, pattern in assertions:
        passed = bool(re.search(pattern, reader.pages[page-1].extract_text(), re.S))
        checks.append(dict(check=f'IRENA_PDF_p{page}_table_row', passed=passed,
                           source_sha256=digest, method_origin='mmj baf1975 prepare_q1_inputs.py'))
    with (root/'data/processed/technology_accounting_parameters.csv').open(encoding='utf-8-sig', newline='') as stream:
        adopted = {r['variable']: r for r in csv.DictReader(stream)
                   if r['source_id'] == 'IRENA_COST_2024_PDF' and r['year'] == '2024'}
    for technology, expected in [('onshore_wind', 856), ('offshore_wind', 1520)]:
        r = adopted[technology+'_installed_cost_weighted_average']
        checks.append(dict(check=technology+'_existing_capex_matches_PDF',
                           passed=float(r['value']) == expected and r['unit'] == '2024 USD/kW'))
    if not all(c['passed'] for c in checks):
        raise ValueError('Existing mmj cost source checks failed')
    cost = []
    for technology, om, cf, ompage, cfpage, omtable, cftable in [
        ('onshore_wind', 29, .33, 209, 76, 'A3', '2.2'),
        ('offshore_wind', 59, .37, 212, 123, 'A6', '4.3')]:
        for variable, value, unit, page, table in [
            ('fixed_om', om, '2024 USD/kW/year', ompage, omtable),
            ('new_project_capacity_factor', cf, 'fraction', cfpage, cftable),
            ('economic_life', 25, 'year', 202, 'A1')]:
            cost.append(dict(year=2024, region='China', variable=technology+'_'+variable,
                value=value, unit=unit, source_id='IRENA_COST_2024_PDF',
                source_locator=f'PDF p{page}; Table {table}; '+
                    ('Wind power economic-life assumption' if variable == 'economic_life' else 'China 2024'),
                status='reviewed_published_assumption' if variable != 'new_project_capacity_factor'
                    else 'reviewed_new_project_parameter',
                boundary='New commissioned projects; CF generally ex ante; country averages not matched project data; '
                         'O&M is a published assumption; not national operating fleet; plant-gate unfirmed electricity',
                missing_reason=''))
    target = root/'data/processed/q1/cost_method_parameters.csv'
    with target.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, list(cost[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(cost)
    return checks
