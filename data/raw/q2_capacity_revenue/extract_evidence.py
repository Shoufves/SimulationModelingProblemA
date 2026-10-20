"""Extract three bounded local originals and reuse existing NEA originals.

No network calls, no model activation, no imputation of capacity-fee inclusion.
"""
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re

import pdfplumber

ROOT = Path(__file__).resolve().parents[3]
DEST = Path(__file__).resolve().parent
LOCAL = [
    ("shanghai_2019_gas_two_part.html", "https://www.shanghai.gov.cn/nw12344/20200813/0001-12344_59562.html",
     ["37.01", "36.50", "0.4802", "2019年9月1日", "2020年9月1日"], "2019-07-11"),
    ("shanghai_2024_capacity_26.html", "https://fgw.sh.gov.cn/fgw_jggl/20240531/07bce8e660f2421bb5fcfee61413f96a.html",
     ["37.01", "36.50", "2024年7月1日", "预结算", "清算"], "2024-05-30"),
    ("guangdong_2023_capacity_1990.html", "https://www.lufengshi.gov.cn/swlufeng/zdly/jghsf/jgzf/zfdt/content/mpost_999871.html",
     ["1990", "每年每千瓦100元", "2024年1月1日", "单独归集", "系统运行费用"], "2023-12-27"),
]


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("p", "br", "div", "tr", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("p", "div", "tr"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_text(path):
    raw = path.read_bytes()
    declaration = re.search(br"charset\s*=\s*[\"']?([\w-]+)", raw[:10000], re.I)
    encoding = declaration[1].decode("ascii") if declaration else "utf-8-sig"
    parser = Text()
    parser.feed(raw.decode(encoding))
    return "\n".join(filter(None, (re.sub(r"\s+", " ", line).strip()
                                  for line in "".join(parser.parts).splitlines())))


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record(path, url, kind):
    raw = path.read_bytes()
    return dict(path=path.relative_to(ROOT).as_posix(), url=url, sha256=sha256(raw).hexdigest(),
                bytes=len(raw), role=kind, admitted_to_model=False)


def main():
    manifest, excerpts = [], []
    for filename, url, anchors, document_date in LOCAL:
        path = DEST / filename
        text = html_text(path)
        compact = re.sub(r"\s+", "", text)
        assert all(re.sub(r"\s+", "", a) in compact for a in anchors), filename
        path.with_suffix(".txt").write_text(text + "\n", encoding="utf-8")
        row = record(path, url, "new_official_local_policy_original")
        row.update(document_date=document_date, verified_text_anchors=anchors)
        manifest.append(row)

    prior = json.loads((ROOT / "data/raw/q2_revenue/source_inventory.json").read_text(encoding="utf-8"))
    originals = {Path(r["path"]).name: r for r in prior}
    for year in ("2013_2014", "2015", "2016", "2017", "2018"):
        name = f"nea_prices_{year}." + ("html" if year in ("2013_2014", "2015") else "pdf")
        source = originals[name]
        path = ROOT / source["path"]
        assert sha256(path.read_bytes()).hexdigest() == source["sha256"], name
        if path.suffix == ".pdf":
            with pdfplumber.open(path) as pdf:
                pages = [(i + 1, page.extract_text() or "") for i, page in enumerate(pdf.pages)]
        else:
            pages = [(0, html_text(path))]
        (DEST / (path.stem + ".txt")).write_text(
            "\n\n".join(f"=== physical page {page} ===\n{text}" for page, text in pages) + "\n",
            encoding="utf-8")
        manifest.append(record(path, source["url"], "reused_original_no_duplicate_download"))
        for page, text in pages:
            compact = re.sub(r"\s+", "", text)
            for keyword in ("容量", "收入", "平均上网电价", "含税", "统计口径"):
                hits = [m.start() for m in re.finditer(keyword, compact)]
                if hits:
                    excerpts.append(dict(source=source["path"], physical_page=page, keyword=keyword,
                        snippets=[compact[max(0, p-100):p+260] for p in hits]))
    dump(DEST / "source_manifest.json", dict(reviewed_on="2026-10-20",
        generated_at=datetime.now(timezone.utc).isoformat(),
        scope="Exactly three new local originals; existing NEA 2013-2018 originals reused",
        production_model_activated=False, sources=manifest))
    dump(DEST / "nea_definition_excerpts.json", excerpts)
    facts = dict(
        status="historical_policy_evidence_not_national_cash_observation",
        shanghai_2019=dict(
            effective_from="2019-09-01", fully_adjusted_from="2020-09-01",
            peaking_capacity_nominal_cny_per_kw_month=37.01,
            chp_capacity_nominal_cny_per_kw_month=36.50,
            peaking_energy_nominal_cny_per_kwh=.4802,
            peaking_9e_first_300_hours_energy_premium_cny_per_kwh=.15,
            chp_energy_hour_bands=[dict(up_to_hours=2500, price=.5044),
                                  dict(up_to_hours=5000, price=.4240),
                                  dict(over_hours=5000, price="Shanghai coal benchmark")],
            distributed_single_part_cny_per_kwh=.7870,
            vat_inclusive=True,
            limitation="Eligible existing/resolved-tariff projects and five named exceptions; staged adjustment; not all gas capacity"),
        shanghai_2024=dict(
            effective_from="2024-07-01", peaking_cny_per_kw_month=37.01,
            chp_cny_per_kw_month=36.50, vat_inclusive=True,
            non_peak_months=[2,3,4,5,6,9,10,11], peak_months=[1,7,8,12],
            capacity_basis="Approved capacity outside summer/winter; declared maximum output within licence in peak months",
            peak_month_deduction_by_event_count={"2":.1,"3":.2,"4":.5,"5_or_more":1.},
            limitation="Own-cause zero-generation months generally receive zero except planned maintenance/normal standby; grid/gas/force-majeure exemptions; provisional payment then true-up"),
        guangdong_2023=dict(
            effective_from="2024-01-01", gas_nominal_cny_per_kw_year=100,
            vat_inclusive=True, capacity_basis="Monthly declared maximum output",
            monthly_rate="annual_rate / 12",
            monthly_deduction_by_event_count={"2":.1,"3":.5,"4_or_more":1.},
            repeated_full_deduction_rule="Three fully deducted months in a natural year cancels eligibility",
            new_plant_start="month after commissioning",
            funding="All provincial industrial/commercial users, proportional to monthly consumption, system operating expense",
            limitation="Compliant in-service public plants only; excludes self-supply/noncompliant plants; actual declarations, deductions and receipts unobserved"),
        nea_capacity_fee_inclusion=dict(
            explicit_definition_years=[2016,2017],
            definition="average feed-in tariff = electricity sales revenue / exported electricity * 1.17",
            explicit_capacity_exclusion_found=False,
            capacity_fee_included_by_province_and_year="unknown",
            inferred_overlap_risk=True,
            modelling_decision="Do not add capacity revenue on top of NEA income-equivalent mean tariff absent reconciled decomposition",
            additional_limit="2018 lacks this formula footnote; 2013-2015 saved HTML is abridged and lacks complete annex definitions"),
    )
    dump(DEST / "policy_facts.json", facts)
    dump(ROOT / "data/catalog/q2_capacity_revenue_review.json", dict(
        reviewed_on="2026-10-20", document="docs/sources/q2_capacity_revenue.md",
        manifest="data/raw/q2_capacity_revenue/source_manifest.json",
        extraction="data/raw/q2_capacity_revenue/extract_evidence.py",
        policy_facts="data/raw/q2_capacity_revenue/policy_facts.json",
        new_original_count=3, reused_nea_original_count=5,
        capacity_fee_included_by_province_and_year="unknown",
        no_capacity_addition_to_nea_mean_without_decomposition=True,
        production_model_activated=False, team_approved=False))
    print(f"Extracted {len(LOCAL)} new originals and {len(manifest)-len(LOCAL)} reused NEA reports")
    for row in excerpts:
        if row["keyword"] in ("容量", "收入", "统计口径"):
            print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
