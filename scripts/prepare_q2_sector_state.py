"""Extract a scoped 2014 balance from the existing CEADs 30-province workbook.

Retains original fuel units, signs, source rows and memo items. It neither fills
Tibet nor converts household petrol into building service or nonenergy feedstocks
into combustion. This intermediate does not initialize or admit a national ABM.
"""
import hashlib
import json
import sys
from math import fsum, isfinite
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from energy_model.q2.io import csvout, dump, local_path, sha


def prepare(root=ROOT):
    try:
        import xlrd
    except ImportError as exc:
        raise RuntimeError('Install requirements-q2-data.txt to read the unchanged original .xls') from exc
    review = json.loads((root/'data/catalog/q2_sector_state_review.json').read_text(encoding='utf-8'))
    for item in review['fingerprints']:
        if sha(local_path(root,item['path'])) != item['sha256']:
            raise ValueError('Sector balance review fingerprint mismatch: '+item['path'])
    source = local_path(root,review['source_path'])
    book = xlrd.open_workbook(source)
    if book.sheet_names() != review['included_sheets']:
        raise ValueError('Historical geographic coverage changed')
    header = book.sheet_by_index(0)
    checks = []
    # 1-based row 60 is a memorandum item, not another conversion process.
    identities = [('final_sector_sum',2,list(range(3,50))),
                  ('conversion_detail_sum',52,[53,54,55,56,57,58,60]),
                  ('reported_total_excludes_losses',64,[2,52])]
    for sheet in book.sheets():
        if (sheet.nrows,sheet.ncols)!=(70,21) or sheet.col_values(0)!=review['row_labels']:
            raise ValueError('Source layout or row labels changed')
        if sheet.row_values(0)!=review['carrier_labels'] or sheet.row_values(1)!=review['unit_labels']:
            raise ValueError('Carrier labels or units changed')
        for check,total,parts in identities:
            for col in range(1,21):
                values=[sheet.cell_value(r,col) for r in [total,*parts]]
                if not all(type(v) in (int,float) and isfinite(v) for v in values):
                    raise ValueError('Missing/non-numeric historical cell; no zero filling')
                residual=fsum(values[1:])-values[0]
                tolerance=.05*len(values)  # Each stored table cell has one decimal.
                checks.append({'sheet':sheet.name,'carrier':sheet.cell_value(0,col),'check':check,
                    'total_cell':f'{xlrd.formula.colname(col)}{total+1}',
                    'detail_cells':';'.join(f'{xlrd.formula.colname(col)}{r+1}' for r in parts),
                    'residual':residual,'rounding_bound':tolerance,'passed':abs(residual)<=tolerance+1e-8})
    if not all(c['passed'] for c in checks):
        raise ValueError('Source balance identities no longer reconcile within declared rounding bound')
    rows=[]
    for row in range(2,70):
        label=header.cell_value(row,0).strip()
        if not label:
            continue
        if row==2: role='final_total_control'
        elif row<50: role='final_sector_detail'
        elif row==52: role='conversion_total_control'
        elif row in (53,54,55,56,57,58,60): role='conversion_detail'
        elif row==62: role='loss_separate_from_reported_total'
        elif row==64: role='reported_total_control'
        else: role='memo_not_additive'
        for col in range(1,21):
            values=[s.cell_value(row,col) for s in book.sheets()]
            if not all(type(v) in (int,float) and isfinite(v) for v in values):
                raise ValueError('Missing sector value; no zero filling')
            rows.append({'year':2014,'geography':'CEADs_30_provinces_excluding_Tibet',
                'account':label,'row_role':role,'carrier':header.cell_value(0,col),'value':fsum(values),
                'unit_as_published':header.cell_value(1,col),'source_cell_each_sheet':f'{xlrd.formula.colname(col)}{row+1}',
                'source_sheet_count':book.nsheets,'source_path':review['source_path'],
                'source_sha256':sha(source),'source_version':'10.6084/m9.figshare.5425615.v1',
                'transformation':'fsum same cell across exactly the reviewed 30 sheets; original units/signs retained',
                'status':'historical_balance_candidate_not_national_initialization'})
    out=root/'data/processed/q2/sector_balance_2014_30province.csv'
    out.parent.mkdir(parents=True,exist_ok=True);csvout(out,rows)
    digest=hashlib.sha256(json.dumps(checks,sort_keys=True,allow_nan=False).encode()).hexdigest()
    summary={'source_sha256':sha(source),'rows':len(rows),'checks':len(checks),
        'all_checks_passed':True,'check_records_digest':digest,
        'maximum_absolute_residual_by_identity':{name:max(abs(c['residual']) for c in checks if c['check']==name)
                                                 for name,_,_ in identities},
        'source_sheets':book.sheet_names(),'excluded_geography':['Tibet','Hong Kong','Macao','Taiwan'],
        'full_national_initialization_admitted':False,
        'inferred_arithmetic_identity_is_not_independent_method_validation':True,
        'output_sha256':sha(out)}
    dump(root/'data/processed/q2/sector_balance_2014_checks.json',summary)
    return summary


if __name__=='__main__': print(json.dumps(prepare(),ensure_ascii=False,indent=2))
