"""Reproduce narrow issuer evidence and provenance; no production-model changes."""
from pathlib import Path
import hashlib
import json
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
SOURCES = {
    "changqing_2020_prospectus": {
        "url": "https://static.cninfo.com.cn/finalpage/2020-04-07/1207458499.PDF",
        "publisher": "广东长青（集团）股份有限公司；巨潮资讯",
        "disclosed": "2020-04-07",
        "pages": [119, 120, 121, 122, 124, 257, 258, 261, 262, 264],
    },
    "changqing_2021": {
        "url": "https://static.cninfo.com.cn/finalpage/2022-03-31/1212747718.PDF",
        "publisher": "广东长青（集团）股份有限公司；巨潮资讯",
        "disclosed": "2022-03-31",
        "pages": [15, 16, 20, 21],
        "use": "scope cross-check only: mixed agroforestry/MSW/coal heat portfolio",
    },
    "sanfeng_2020_ipo_summary": {
        "url": "https://static.cninfo.com.cn/finalpage/2020-05-20/1207835086.PDF",
        "publisher": "重庆三峰环境集团股份有限公司；巨潮资讯",
        "disclosed": "2020-05-20",
        "pages": [114],
    },
    "sanfeng_2023_bond": {
        "url": "https://static.sse.com.cn/disclosure/bond/announcement/company/c/new/2023-12-11/240410_20231211_N9UW.pdf",
        "publisher": "重庆三峰环境集团股份有限公司；上海证券交易所",
        "disclosed": "2023-12-11",
        "pages": [110, 111, 112, 113, 114],
    },
}

def run():
    for name, source in SOURCES.items():
        path = ROOT / f"{name}.pdf"
        source["file"] = path.name
        source["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        reader = PdfReader(path)
        source["pdf_pages"] = len(reader.pages)
        text = "\n".join(
            f"\n=== PDF PAGE {n} ===\n" + (reader.pages[n - 1].extract_text() or "")
            for n in source["pages"]
        )
        (ROOT / f"{name}_selected.txt").write_text(text, encoding="utf-8")
    observations = {
        "status": "research_only; company/project samples, not national estimates",
        "agroforestry": {
            "fuel_purchase_cny_per_t": [
                {"period": "2016", "value": 245.69},
                {"period": "2017", "value": 284.43},
                {"period": "2018", "value": 311.39},
                {"period": "2019H1", "value": 291.29},
            ],
            "fuel_locator": "changqing_2020_prospectus PDF/printed p124; VAT basis not expressly labelled in table",
            "ningan_heat": [
                {"period": p, "heat_gj": q, "revenue_cny": r*10000, "derived_cny_per_gj": r*10000/q}
                for p, q, r in [
                    ("2016", 41023.33, 108.91),
                    ("2017", 182268.20, 487.79),
                    ("2018", 205262.48, 557.11),
                    ("2019H1", 127495.53, 348.05),
                ]
            ],
            "heat_locator": "changqing_2020_prospectus PDF/printed p120; Ningan 30MW only",
            "capex_projects": [
                {
                    "name": name, "mw": 35, "total_cny": cost*10000,
                    "idc_cny": idc*10000, "initial_working_capital_cny": wc*10000,
                    "derived_total_cny_per_kw": cost*10000/35000,
                    "derived_ex_idc_and_working_capital_cny_per_kw": (cost-idc-wc)*10000/35000,
                    "locator": locator,
                }
                for name, cost, idc, wc, locator in [
                    ("铁岭", 39556, 1429, 4470, "changqing_2020_prospectus PDF/printed pp257–258"),
                    ("永城", 39202, 1398, 4891, "changqing_2020_prospectus PDF/printed pp261–262"),
                ]
            ],
        },
        "msw": {
            "treatment_service_fee_cny_per_t": [50, 105],
            "service_fee_scope": "Sanfeng operating projects at end-2022; contract price, monthly/quarterly settlement with local government; VAT not expressly stated",
            "service_fee_locator": "sanfeng_2023_bond PDF p112 / printed p111",
            "electricity": [
                {"year": y, "gross_kwh": g*10000, "export_kwh": e*10000,
                 "reported_gross_kwh_per_t": k,
                 "derived_export_fraction": e/g,
                 "conditional_export_kwh_per_same_t": k*e/g}
                for y,g,e,k in [
                    (2020,323770.32,284985.5,394.79),
                    (2021,419466.80,367985.56,408.52),
                    (2022,502422.90,440506.60,422.06),
                ]
            ],
            "electricity_locator": "sanfeng_2023_bond PDF p111 / printed p110; excludes heat-only project in per-tonne statement (PDF p114)",
            "warning": "Do not reconstruct a paired per-tonne factor from all-company reception or furnace tonnes: their scopes differ from the reported generation-intensity denominator.",
            "capex_projects": [
                {"name": name, "total_cny": cost*10000, "additional_t_per_day": t,
                 "derived_cny_per_t_day": cost*10000/t}
                for name,cost,t in [
                    ("重庆洛碛",200803.64,3000),("汕尾二期",56000,1400),("东营二期",23986.03,600)
                ]
            ],
            "capex_locator": "sanfeng_2020_ipo_summary PDF p114 / printed p113; project total investment, not just equity or raised funds",
        },
    }
    (ROOT / "source_manifest.json").write_text(json.dumps(SOURCES, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "evidence.json").write_text(json.dumps(observations, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(observations, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    run()
