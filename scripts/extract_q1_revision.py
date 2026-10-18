"""Reviewed existing originals for C1/L2; explicit, never automatic input admission."""
from pathlib import Path
import hashlib
import json
from pypdf import PdfReader
from extract_q1_additions import record, writecsv, prices, EVID

ROOT = Path(__file__).resolve().parents[1]


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    originals = {
        'china_ndc_2035.pdf': 'ae37d01d21bfb33df2ed2dcbde2d423bca4075c9bfe150a2408461a70cb73b9d',
        'storage_2025.pdf': '47c97e8afc308653fd47dc6a174915499189a10c295b23c8f9d96e45906ac6c3',
    }
    for name, expected in originals.items():
        p = ROOT/'data/raw/lb/base/reports'/name
        if hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError('Reviewed original changed: '+name)
    ndc = PdfReader(ROOT/'data/raw/lb/base/reports/china_ndc_2035.pdf').pages[4].extract_text()
    if not all(s in ndc for s in ['19.8%', '初步测算', '2024']):
        raise ValueError('NDC text check failed')
    rows = [record('nonfossil_primary_consumption_share', 19.8, '%', 'lb/base:NDC_2035',
                   'PDF physical p5 / printed p3; 2030 NDC progress paragraph',
                   status='published_preliminary', publication_year=2025, precision_role='selected_observation',
                   boundary='2024 preliminary estimate in 2035 NDC release; China national reporting scope, used for mainland Q1; not merged with NBS primary electricity and other, not an independent validation sample; other years missing')]
    # Figure 1: all 12 labels visually reviewed against rendered physical p21.
    for year, power, energy, duration in [(2021,400,800,2.0),(2022,870,1805,2.1),
                                         (2023,3139,6687,2.1),(2024,7376,16820,2.3)]:
        for var, value, unit in [('new_storage_power',power/100,'GW'),
                                 ('new_storage_energy',energy/100,'GWh'),
                                 ('new_storage_duration_published',duration,'h')]:
            rows.append(record(var,value,unit,'lb/base:NEA_STORAGE_2025',
                               f'PDF physical p21 / printed p011; Figure 1; {year}',year=year,
                               publication_year=2025,precision_role='selected_observation',
                               boundary='Built and operating new storage, excludes pumped hydro; figure power/energy divided by 100 from 10^4 kW/kWh. Published rounded duration, not guaranteed dispatch duration; not SOC/efficiency. Same-source series, not independent observations of text and figure.'))
    rows.append(record('new_storage_energy_text_rounded',168,'GWh','lb/base:NEA_STORAGE_2025',
                       'PDF physical pp20-21 / printed pp010-011; body 1.68 hundred million kWh',
                       status='same_source_rounded_crosscheck',publication_year=2025,precision_role='crosscheck_only',
                       boundary='Same 2024 energy as Figure 1 168.2 GWh, rounded body 168 GWh; not added, averaged or handed off as a second capacity candidate'))
    for region,power,energy in [('华北',22.24,49.42),('西北',18.71,52.01)]:
        for var,value,unit in [('new_storage_power',power,'GW'),('new_storage_energy',energy,'GWh')]:
            rows.append(record(var,value,unit,'lb/base:NEA_STORAGE_2025',
                               'PDF physical p21 / printed p011; regional paragraph',region=region,
                               publication_year=2025,precision_role='selected_observation',
                               boundary='Regional subset of national total, not additional capacity; no province allocation; nameplate, not available SOC'))
    for region,value in [('华北',30.1),('西北',25.4),('华东',16.9),('华中',14.7),('南方',12.4),('东北',0.5)]:
        rows.append(record('new_storage_power_share',value,'%','lb/base:NEA_STORAGE_2025',
                           'PDF physical p21 / printed p011; Figure 2',region=region,
                           publication_year=2025,precision_role='selected_observation',
                           boundary='Rounded regional shares of national installed power; regional buckets as published, not provincial/energy shares; no double count with national capacity'))
    writecsv('reviewed_2024_additions.csv',rows)
    prices()
    evidence=dict(review_date='2026-10-18',reviewer='lb local source recheck; external re-review pending',
                  original_sha256=originals,scope='C1, C2, L2; originals unchanged; uses remain Q1 candidates',
                  visual_checks=['NDC physical p5: preliminary 2024 19.8%',
                                 'Storage physical p21: Figure 1 2021-2024 12 labels; body 168 vs figure 168.2 GWh; two regional scales and six regional power shares'],
                  storage_conversion='10^4 kW /100 = GW; 10^4 kWh /100 = GWh; 1.68*100 =168 GWh',
                  storage_precision='168.2 selected; 168 retained crosscheck only; duration 2.3 published not derived',
                  price_definitions=['Europe archive Description!B12: April 2015 TTF, mixed 2015 excluded from returns',
                                     'Coal archive Description!B4: January 2015 6000 kcal/kg spot',
                                     'January 2023/January 2024/February 2025 PDFs p3: replacement from February 2022, mixed 2022; 2021 pre-switch, 2023-2024 futures'],
                  source_texts='Adjacent *_p*.txt; storage_p21.png and ndc_p5.png are visual review renders')
    (EVID/'source_review.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Reviewed {len(rows)} new scoped observations; price definitions segmented')


if __name__=='__main__':main()
