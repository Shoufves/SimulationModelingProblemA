"""Reproduce reviewed 2014 national accounts without silently reconciling vintages."""
import csv
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from energy_model.q2.io import csvout, dump, local_path, sha


def prepare(root=ROOT):
    review = json.loads((root/'data/catalog/q2_nbs2014_review.json').read_text(encoding='utf-8'))
    if review['decision'] != 'historical_accounts_and_boundary_diagnostics_only' or not all(
            c['passed'] is True and c['evidence'] for c in review['checks']):
        raise ValueError('National historical accounts review unresolved')
    for item in review['fingerprints']:
        if sha(local_path(root, item['path'])) != item['sha256']:
            raise ValueError('Historical accounts fingerprint mismatch: '+item['path'])
    source = json.loads((root/'data/catalog/q2_nbs2014_transcription.json').read_text(encoding='utf-8'))
    rows, cells, checks = [], {}, []
    for table in source['tables']:
        if sha(local_path(root, table['source_path'])) != table['source_sha256']:
            raise ValueError('Original national account image changed')
        for cell in table['cells']:
            key = (table['table'], cell['account'])
            if key in cells:
                raise ValueError('Duplicate national account cell')
            cells[key] = cell
            raw = cell['raw_value']
            value = Decimal(raw) if raw is not None else None
            if value is not None and not value.is_finite():
                raise ValueError('Invalid national account value')
            rows.append({'year':source['statistical_year'], 'edition':source['edition'],
                         'geography':source['geography'], 'table':table['table'], 'account':cell['account'],
                         'value':raw, 'unit':cell.get('unit',table['default_unit']),
                         'source_label':cell['source_label'], 'source_column':cell.get('source_column','2014'),
                         'source_key':table['source_key'], 'source_path':table['source_path'],
                         'source_sha256':table['source_sha256'], 'source_notes':table['notes'],
                         'annual_information_available_from':source['annual_information_available_from'],
                         'transformation':'identity; original unit and sign retained',
                         'status':'original_blank' if raw is None else 'reviewed_historical_account',
                         'missing_reason':'Source cell blank; not interpreted as zero' if raw is None else ''})

    def value(table, account):
        raw = cells[table,account]['raw_value']
        if raw is None:
            raise ValueError('Cannot use missing account as zero')
        return Decimal(raw)

    def check(table, identity, terms):
        # Worst-case rounding of independently printed cells, not a fitted tolerance.
        residual = Decimal(0); tolerance = Decimal(0)
        for account, sign in terms:
            v = value(table,account)
            residual += sign*v
            tolerance += abs(sign)*Decimal(5).scaleb(v.as_tuple().exponent-1)
        checks.append({'table':table,'identity':identity,'terms':dict(terms),
                       'residual':str(residual),'rounding_bound':str(tolerance),
                       'passed':abs(residual)<=tolerance})

    sectors = ['agriculture','industry','construction','transport','trade','other','household']
    for table in ('0903CH','0904CH','0905CH'):
        check(table,'supply = production + imports - exports + inventory draw',
              [('supply',1),('production',-1),('imports',-1),('exports',1),('inventory_draw',-1)])
        check(table,'supply - consumption = statistical difference',
              [('supply',1),('consumption',-1),('statistical_difference',-1)])
    for table in ('0903CH','0904CH','0905CH','0906CH'):
        check(table,'consumption = sum of seven broad sectors',
              [('consumption',1)]+[(s,-1) for s in sectors])
    check('0903CH','consumption = final + conversion loss + loss - recovered energy',
          [('consumption',1),('final',-1),('transformation_loss',-1),('loss',-1),('recovery',1)])
    for table in ('0904CH','0905CH'):
        check(table,'consumption = final + intermediate + loss',
              [('consumption',1),('final',-1),('intermediate',-1),('loss',-1)])
    check('0906CH','supply = production + imports - exports',
          [('supply',1),('production',-1),('imports',-1),('exports',1)])
    check('0906CH','consumption = final + transmission/distribution loss',
          [('consumption',1),('final',-1),('loss',-1)])
    # Only columns with seven observed cells can be checked as complete sums.
    incomplete_columns = []
    for carrier in ('energy','coal','coke','crude','gasoline','kerosene','diesel','fuel_oil','gas','electricity'):
        if any(cells['0909CH',s+':'+carrier]['raw_value'] is None for s in sectors):
            incomplete_columns.append(carrier)
            continue
        check('0909CH','sector sum: '+carrier,[('total:'+carrier,1)]+[(s+':'+carrier,-1) for s in sectors])
    if not all(c['passed'] for c in checks):
        raise ValueError('National account arithmetic outside rounding bounds: '+str([c for c in checks if not c['passed']]))

    with (root/'data/processed/unified/nbs_history.csv').open(encoding='utf-8-sig',newline='') as f:
        later = [r for r in csv.DictReader(f) if r['year']=='2014' and r['variable']=='consumption_10ktce']
    if len(later)!=1 or later[0]['edition']!='NBS_2025' or later[0]['region']!='China_mainland':
        raise ValueError('Expected unique revised 2014 NBS total with reviewed boundary')
    with (root/'data/processed/q2/sector_balance_2014_30province.csv').open(encoding='utf-8-sig',newline='') as f:
        provincial = [r for r in csv.DictReader(f) if r['account']=='Total Final Consumption' and r['carrier']=='Electricity']
    if len(provincial)!=1 or provincial[0]['year']!='2014':
        raise ValueError('Expected unique CEADs final electricity comparison')
    p=provincial[0]
    # The provincial file's printed 10^8 kWh unit is independently checked below.
    if p['unit_as_published']!='108 kwh':
        raise ValueError('Provincial electricity unit differs from reviewed original')
    old_total=value('0909CH','total:energy');new_total=Decimal(later[0]['value'])
    final_electricity=value('0906CH','final');province_electricity=Decimal(p['value'])
    diagnostics=[
        {'comparison':'NBS edition revision, 2014 consumption','left_value':str(new_total),'right_value':str(old_total),
         'difference_left_minus_right':str(new_total-old_total),'unit':'10^4 tce',
         'left_source':later[0]['source_key'],'right_source':'lb/base:NBS_ARCHIVE_2016_0909CH',
         'status':'vintage_difference_not_reconciled','implication':'Do not scale 2016 sector cells to 2025 total without a separate statistical bridge.'},
        {'comparison':'30-province vs national final electricity, 2014','left_value':str(province_electricity),
         'right_value':str(final_electricity),'difference_left_minus_right':str(province_electricity-final_electricity),
         'unit':'10^8 kWh','left_source':p['source_path'],'right_source':'lb/base:NBS_ARCHIVE_2016_0906CH',
         'status':'geography_and_vintage_difference_not_reconciled',
         'implication':'A larger 30-province total cannot be explained by adding missing Tibet alone; do not force residual allocation.'},
        {'comparison':'Generation total minus four reported technology subtotals','left_value':str(value('0906CH','production')),
         'right_value':str(sum(value('0906CH',k) for k in ('hydro','thermal','nuclear','wind'))),
         'difference_left_minus_right':str(value('0906CH','production')-sum(value('0906CH',k) for k in ('hydro','thermal','nuclear','wind'))),
         'unit':'10^8 kWh','left_source':'lb/base:NBS_ARCHIVE_2016_0906CH','right_source':'same table',
         'status':'unclassified_generation_residual','implication':'Do not label the residual solar or zero.'},
        {'comparison':'Electricity supply minus consumption','left_value':str(value('0906CH','supply')),
         'right_value':str(value('0906CH','consumption')),
         'difference_left_minus_right':str(value('0906CH','supply')-value('0906CH','consumption')),
         'unit':'10^8 kWh','left_source':'lb/base:NBS_ARCHIVE_2016_0906CH','right_source':'same table',
         'status':'published_balance_discrepancy','implication':'Preserve published discrepancy; do not modify original consumption or generation.'}]
    out=root/'data/processed/q2';out.mkdir(parents=True,exist_ok=True)
    csvout(out/'nbs2014_accounts.csv',rows)
    csvout(out/'nbs2014_boundary_diagnostics.csv',diagnostics)
    dump(out/'nbs2014_checks.json',{'passed':True,'arithmetic_checks':checks,
         'columns_not_summed_because_missing':incomplete_columns,'records':len(rows),
         'source_review_sha256':sha(root/'data/catalog/q2_nbs2014_review.json'),
         'model_admission':False,'missing_cells':sum(r['status']=='original_blank' for r in rows)})
    return {'records':len(rows),'checks':len(checks),'diagnostics':len(diagnostics),'national_model_admission':False}


if __name__=='__main__':
    print(json.dumps(prepare(),ensure_ascii=False,indent=2))
