"""Offline extraction of NEA2014 construction table and NNSA unit states."""
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from energy_model.q2.io import csvout, dump, local_path, sha, verify_source_records


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.table, self.row, self.cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'table': self.table = []
        if tag == 'tr': self.row = []
        if tag in ('td', 'th'): self.cell = []

    def handle_data(self, value):
        if self.cell is not None and value.strip(): self.cell.append(value.strip())

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            if self.row is not None: self.row.append(' '.join(self.cell))
            self.cell = None
        if tag == 'tr' and self.row is not None:
            if self.table is not None: self.table.append(self.row)
            self.row = None
        if tag == 'table' and self.table is not None:
            self.tables.append(self.table); self.table = None


def prepare(root=ROOT):
    review = json.loads((root / 'data/catalog/q2_nuclear_queue_review.json').read_text(encoding='utf-8'))
    if review['decision'] != 'scoped_2014_nuclear_queue_reference' or not review['checks'] or not all(c['passed'] and c['evidence'] for c in review['checks']):
        raise ValueError('Nuclear queue reference review unresolved')
    for item in review['fingerprints']:
        if sha(local_path(root, item['path'])) != item['sha256']:
            raise ValueError('Nuclear queue reference changed: ' + item['path'])
    verify_source_records(root, review['source_records'])
    p = Tables()
    source = root / 'data/raw/q2/nea_nuclear_2014_qa.html'
    p.feed(source.read_text(encoding='utf-8'))
    tables = [t for t in p.tables if t and t[0] == ['核电厂名称', '机组号', '堆型', '容量万千瓦', '开工时间']]
    if len(tables) != 1: raise ValueError('Missing or ambiguous NEA nuclear table')
    table = tables[0]
    if table[-1] != ['合计', '26 台', '', '2845', '']: raise ValueError('NEA table control changed')
    names = {'红沿河核电厂':'hongyanhe', '宁德核电厂':'ningde', '福清核电厂':'fuqing', '阳江核电厂':'yangjiang',
             '秦山核电厂扩建（方家山）':'fangjiashan', '三门核电厂':'sanmen', '海阳核电厂':'haiyang', '台山核电厂':'taishan',
             '海南昌江核电厂':'changjiang', '防城港核电厂':'fangchenggang', '石岛湾核电厂':'shidaowan', '田湾核电厂':'tianwan'}
    transcription = json.loads((root / 'data/catalog/q2_nuclear_queue_status_transcription.json').read_text(encoding='utf-8'))
    states = {r['id']:r for r in transcription['observations']}
    if len(states) != len(transcription['observations']): raise ValueError('Duplicate unit state')
    rows = []
    for index, row in enumerate(table[1:-1], 1):
        site = names[row[0].replace(' ', '')]
        units = [int(s) for s in re.findall(r'(\d+)\s*号', row[1])]
        capacity = re.fullmatch(r'(\d+)\s*×\s*(\d+)', row[3])
        dates = re.findall(r'(\d{4})\s*年\s*(\d+)\s*月', row[4])
        if not capacity or int(capacity[1]) != len(units) or len(dates) != len(units):
            raise ValueError('NEA row count, capacity or date mismatch')
        for unit, (year, month) in zip(units, dates):
            identity = f'{site}_{unit}'
            state = states[identity]
            rows.append({'id':identity, 'site':site, 'unit':unit, 'reactor_type':row[2],
                'capacity_MW':int(capacity[2]) * 10, 'capacity_basis':'reported ten-thousand-kW; net/gross basis not separately stated',
                'construction_start_month':f'{int(year):04d}-{int(month):02d}', 'reference_date':'2014-12-31',
                'source_path':source.relative_to(root).as_posix(), 'source_sha256':sha(source),
                'source_locator':f'question33 table site row{index}, unit{unit}',
                'status_source_path':'data/raw/q2/nnsa_annual_2014.pdf',
                'status_physical_page':state['physical_page'], 'status':state['status'], 'event_date':state['event_date'],
                'diagnostic_stage':state['diagnostic_stage'], 'stage_basis':state['stage_status'],
                'remaining_years':None, 'remaining_cost':None, 'online_year':None,
                'admission':'reviewed_queue_reference_not_complete_national_state'})
    if len(rows) != 26 or len({r['id'] for r in rows}) != 26 or sum(r['capacity_MW'] for r in rows) != 28450:
        raise ValueError('Nuclear queue fails original total')
    if set(states) != {r['id'] for r in rows}: raise ValueError('Unmatched status or unit')
    if {r['id'] for r in rows} & {r['id'] for r in transcription['excluded_operating_units']}:
        raise ValueError('Operating unit duplicated as new construction')
    out = root / 'data/processed/q2'
    csvout(out / 'nuclear_queue_2014_reference.csv', rows)
    checks = {'units':26, 'capacity_MW':28450, 'source_total_reproduced':True,
              'NEA_question34_operating_MW':20100, 'NBS2025_2014_nuclear_MW':20080,
              'opening_vintage_difference_MW':20, 'opening_vintage_difference_reconciled':False,
              'remaining_duration_cost_or_actual_online_dates_admitted':False,
              'scope':'Historical queue reference; explicit timing/funding hypotheses required for model use'}
    dump(out / 'nuclear_queue_2014_checks.json', checks)
    return checks


if __name__ == '__main__': print(json.dumps(prepare(), ensure_ascii=False, indent=2))
