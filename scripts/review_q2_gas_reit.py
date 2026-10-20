"""Reproduce a single disclosed gas-project revenue decomposition, not China."""
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import pdfplumber

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/"data/raw/q2_gas_reit"
PDF=FOLDER/"penghua_energy_2025_annual.pdf"
HASH="3dcb3818e94760a553aebe5c5db8f8fd893a5f79c28561f9d4677677768fc88b"
URL="https://dataclouds.cninfo.com.cn/sjother2/fund/2026/20260331/1f11af20f3144ed8a3ddf329c7149a47.pdf"


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n","utf-8")


def extract():
    if sha256(PDF.read_bytes()).hexdigest()!=HASH:
        raise ValueError("Gas project report original differs")
    with pdfplumber.open(PDF) as doc:
        text=[p.extract_text() or "" for p in doc.pages]
    if len(text)!=103 or "2025 年年度报告" not in text[0]:
        raise ValueError("Unexpected report period/page count")
    p16,p17=text[15],text[16]
    if "电力销售、商品销售收入按13%的税率计算销项税" not in text[68]:
        raise ValueError("Missing project-company electricity VAT disclosure")
    for value in ("315,108.75","351,198.65","1,352,933,480.27","1,560,469,240.08","0.4852","0.5021"):
        if value not in p16:raise ValueError("Missing operating table value: "+value)
    labels=["电网代购及跨省交易","年度双边协商","月度双边协商","月度转让","现货","其他电费收入","容量电费"]
    expected=["4,213.95","84,047.61","765.31","-3,747.79","29,397.16","8,584.37","12,032.73"]
    entries=[]
    for i,(label,value) in enumerate(zip(labels,expected),1):
        match=re.search(r"（"+str(i)+r"）(.*?)(?=（"+str(i+1)+r"）|4\.1\.5)",p17,re.S)
        if not match or label not in match[1] or value not in match[1]:
            raise ValueError("Missing/reordered sales decomposition: "+label)
        amount=Decimal(value.replace(",",""))*10000
        entries.append(dict(category=label,revenue_nominal_cny_ex_vat=float(amount),
            reported_unit="10k CNY excluding VAT",physical_page=17))
    total=Decimal("1352933480.27")
    reported_sum=sum(Decimal(str(r["revenue_nominal_cny_ex_vat"])) for r in entries)
    # Seven lines rounded to 0.01 ten-thousand yuan: at most 50 yuan each.
    residual=reported_sum-total
    if abs(residual)>Decimal("350"):raise ValueError("Revenue decomposition does not reconcile within printed rounding")
    exports=Decimal("315108.75")*10000
    cap=Decimal("12032.73")*10000
    other=Decimal("8584.37")*10000
    if abs(total/exports*Decimal("1.13")-Decimal(".4852"))>Decimal(".00005"):
        raise ValueError("Reported mean tariff fails revenue/volume definition")
    return dict(status="verified_single_project_mechanism_evidence_not_national_calibration",
        entity="深圳市东部电力有限公司；鹏华深圳能源REIT底层项目",
        report_year=2025,report_sent_date="2026-03-30",retrieved_date="2026-10-20",
        source_path=PDF.relative_to(ROOT).as_posix(),source_sha256=HASH,source_url=URL,
        visually_reviewed_physical_pages=[16,17,69],source_page_count=103,
        electricity_sales_vat_rate=.13,electricity_sales_vat_physical_page=69,
        revenue_components=entries,total_revenue_nominal_cny_ex_vat=float(total),
        net_exports_kwh=float(exports),reported_mean_tariff_cny_per_kwh_inc_vat=.4852,
        rounding_residual_cny=float(residual),
        derived=dict(capacity_revenue_share=float(cap/total),
            mean_total_revenue_per_net_kwh_ex_vat=float(total/exports),
            mean_without_capacity_revenue_per_net_kwh_ex_vat=float((total-cap)/exports),
            mean_without_capacity_and_other_revenue_per_net_kwh_ex_vat=float((total-cap-other)/exports)),
        comparisons_2024=dict(total_revenue_nominal_cny_ex_vat=1560469240.08,
            net_exports_kwh=3511986500,reported_mean_tariff_cny_per_kwh_inc_vat=.5021,
            capacity_revenue="not_separately_reported_in_the_reviewed_comparison_table"),
        admitted_use="Mechanism/decomposition example and double-counting diagnostic only",
        prohibited_uses=["No national weighting or extrapolation of this project share",
            "No retroactive 2015-2024 policy or revenue inputs from 2025 rules",
            "No equation of accrued operating revenue with same-year cash receipts",
            "No claim that this report identifies NEA 2013-2018 income composition",
            "No use of valuation forecasts as realised revenue observations"],
        model_parameters_changed=False)


def main():
    evidence=extract()
    save(FOLDER/"evidence.json",evidence)
    save(FOLDER/"source_manifest.json",dict(sources=[dict(id="penghua_energy_reit_2025_annual",
        title="鹏华深圳能源清洁能源封闭式基础设施证券投资基金2025年年度报告",
        publisher="鹏华基金管理有限公司；巨潮资讯披露原件",url=URL,
        path=PDF.relative_to(ROOT).as_posix(),sha256=HASH,bytes=PDF.stat().st_size,
        retrieved_date="2026-10-20",status="verified_project_revenue_decomposition_only",
        notes="2025 single Guangdong gas project; includes 2024 aggregate comparison only. No national historical calibration admission.")]))
    print(json.dumps({k:evidence[k] for k in ("status","rounding_residual_cny","derived")},ensure_ascii=False))


if __name__=="__main__":main()
