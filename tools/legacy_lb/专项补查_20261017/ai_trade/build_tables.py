"""Transcribe visually verified published tables; preserve rounding and blanks."""
import csv, json
from pathlib import Path

P = Path(__file__).resolve().parent
D = P / 'derived'
D.mkdir(exist_ok=True)

def save(name, rows):
    with (D/name).open('w', encoding='utf-8-sig', newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

oil=[('俄罗斯',17),('沙特阿拉伯',14),('伊拉克',11),('马来西亚',11),('巴西',8),('阿联酋',7),('阿曼',6),('安哥拉',5),('科威特',3),('加拿大',3),('印度尼西亚',3),('其他',12)]
save('china_crude_origin_2025.csv',[dict(year=2025,origin=n,share_percent=v,source_id='SHFE_OIL_2026',pdf_page=23,printed_page=20,precision='rounded integer chart label') for n,v in oil])
assert sum(v for _,v in oil)==100

# GIIGNL 2026 report PDF page 11, printed pages 18-19, China row.
# Blank source cells are retained as missing/not printed, never converted to zero.
lng=[('Algeria',0.1),('Angola',None),('Cameroon',None),('Congo',None),('Egypt',None),('Equatorial Guinea',0.2),('Mauritania',0.1),('Mexico',None),('Nigeria',1.2),('Norway',None),('Russia Europe',5.1),('Trinidad & Tobago',0.3),('USA',0.3),('Atlantic Basin',7.2),('Oman',1.4),('Qatar',20.2),('UAE',0.4),('Middle East',22.1),('Australia',21.2),('Brunei',0.4),('Canada',0.4),('Indonesia',3.7),('Malaysia',7.2),('Mozambique',0.2),('Papua New Guinea',2.4),('Peru',0.2),('Russia Asia',2.4),('Pacific Basin',38.0),('Net Reloads Received',-0.3),('Grand Total',67.0)]
totals={'Atlantic Basin','Middle East','Pacific Basin','Grand Total'}
save('china_lng_origin_2025.csv',[dict(year=2025,origin=n,value_mt=v,cell_status='blank_in_original' if v is None else 'reported_rounded',row_type='aggregate' if n in totals else ('adjustment' if n=='Net Reloads Received' else 'origin'),source_id='GIIGNL_2026',pdf_page=11,printed_pages='18-19') for n,v in lng])
assert abs(7.2+22.1+38.0-0.3-67.0)<1e-8

save('compute_electricity_anchors.csv',[
 dict(year=2025,value_twh=170,type='reported past-year value',coverage='national compute centers; NOT AI-only',source_id='NEA_COMPUTE_2025',notes='NEA website reprints Peoples Daily Overseas Edition reporting NEA meeting; nationwide boundary not separately enumerated'),
 dict(year=2030,value_twh=800,type='projection',coverage='national compute centers; NOT AI-only',source_id='NEA_COMPUTE_2025',notes='projection; not observed or compulsory baseline')])

entries=json.loads((P/'sources.json').read_text(encoding='utf-8'))
keys=['id','title','agency','coverage','url','file','status','bytes','sha256','notes','error']
with (P/'资料来源目录.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,keys,extrasaction='ignore');w.writeheader();w.writerows(entries)
print('Created 3 tables; oil shares and LNG aggregate arithmetic passed.')
