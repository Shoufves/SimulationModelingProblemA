"""Record visual tax-basis evidence and link it to archived provincial CTCI rows."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from collect_q2_coal_prices_extension import Page

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data/raw/q2_coal_tax_basis"


def main():
    manifest = json.loads((FOLDER / "source_manifest.json").read_text("utf-8"))
    for source in manifest:
        assert sha256((ROOT / source["path"]).read_bytes()).hexdigest() == source["sha256"]
    # Manually transcribed from visually inspected PDF36, printed正文28,
    # of the 2020 valuation report. No national observations are generated.
    report_values = {
        2017: [519.69, 482.57, 476.82, 450.36, 465.94, 498.51, 462.13, 499.91, 513.91, 555.55, 522.8, 487.05],
        2018: [467.09, 388.74, 421.98, 447.52, 482.76, 513.48, 510.29, 530.24, 540, 541.58, 549.68, 569.41],
        2019: [523.45, 522.03, 478.96, 456.68, 489.41, 442.36, 487.76, 505.44, 498.07, 457.68, 442.19],
    }
    overlaps = []
    overlap_hashes = {}
    for year, values in report_values.items():
        relative = f"data/raw/q2_coal_prices_extension/guizhou_{year}_full.html"
        raw = (ROOT / relative).read_bytes()
        page = Page()
        page.feed(raw.decode("utf-8"))
        row = next(r for r in page.rows if r[0] == "云南省")
        for month, value in enumerate(values, 1):
            assert float(row[month]) == value
            overlaps.append(dict(year=year, month=month, value=value, archived_source=relative))
        overlap_hashes[relative] = sha256(raw).hexdigest()
    evidence = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "secondary_documentary_evidence_not_direct_compilation_original",
        "reports": [
            dict(id=manifest[0]["id"], pages=79, evaluator="北京汇贤达评估咨询有限公司",
                 title="宣威市宝安丰矿业有限公司保安煤矿采矿权出让收益评估报告",
                 price_table_pdf_page=47, price_table_printed_page=39,
                 table_scope="Yunnan provincial electricity-coal price index, June2016-May2019",
                 table_header="元/吨，含税含运费",
                 compilation_description="Report attributes tax-inclusive delivered-to-plant basis to NDRC compilation description",
                 appendix_reference="Body cites 附件十六; PDF8 contents instead identifies mining-right valuation/contract/payment materials",
                 direct_compilation_screenshot_found=False,
                 public_pdf_tail_review="PDF62-79: signature, report/table covers, table contents and financial valuation tables; no actual attachment16 or NDRC compilation screenshot"),
            dict(id=manifest[1]["id"], pages=63, evaluator="云南君信资产评估有限公司",
                 title="宣威市慈罡矿业有限责任公司田坝镇海子煤矿采矿权出让收益评估报告",
                 report_number="云君信矿评字[2020]第007号", report_date="2020-01-16",
                 price_table_pdf_page=36, price_table_printed_page=28, table_number="11-1",
                 table_scope="Yunnan provincial electricity-coal price index, December2016-November2019",
                 table_header="元/吨，含税含运费",
                 compilation_description="Report attributes tax-inclusive delivered-to-plant basis to NDRC compilation description",
                 direct_compilation_screenshot_found=False,
                 text_layer="Scanned PDF; table and text visually read, not searchable text extraction"),
        ],
        "archived_provincial_table_overlap_count": len(overlaps),
        "all_overlap_values_match": True, "overlaps": overlaps,
        "scope_conclusions": {
            "tax_included": "Supported by explicit secondary report table headings and narrative, not direct NDRC compilation original",
            "freight_included": "Explicitly stated for the reports' Yunnan CTCI tables",
            "5000_kcal_per_kg": "Not independently established by these valuation reports; retain separately verified index-source definition",
            "national_scope": "35 exact provincial overlaps link the reports to the archived same CTCI family; applying provincial tax wording to national methodology remains an inference",
            "procurement_weights": "No national generating-sector purchase weights established",
            "VAT_deduction": "No proof of a uniform deductible VAT fraction for delivered composite coal+freight, all purchasers, or all years",
        },
        "limitations": [
            "Public hosting by a natural resources department does not make a privately authored appraisal an NDRC original",
            "Two evaluators cite the same index; these are not independent monthly price observations",
            "The reports' tax reforms and local freight estimates are valuation assumptions, not nationwide invoice microdata",
            "No automatic price conversion, parameter fitting, VAT subtraction or default admission is performed",
        ],
        "source_sha256": {s["path"]: s["sha256"] for s in manifest},
        "overlap_source_sha256": overlap_hashes,
        "default_inputs_changed": False, "scientific_acceptance": False,
    }
    target = FOLDER / "evidence.json"
    if target.exists():
        raise ValueError("Preserve existing evidence")
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", "utf-8")
    receipt = ROOT / "outputs/validation/coal_tax_basis_independent_review_20261020.json"
    assert not receipt.exists()
    receipt.write_text(json.dumps(dict(
        created_at=evidence["created_at"], status=evidence["status"],
        verified_originals=2, visually_reviewed_2019_pdf_pages=[8, 47, 65],
        visually_reviewed_2019_tail_thumbnail_pages=list(range(62, 80)),
        visually_reviewed_2020_pdf_pages=[2, 36],
        direct_ndrc_compilation_found=False, provincial_overlap_count=len(overlaps),
        all_provincial_overlap_values_match=True,
        evidence_path=target.relative_to(ROOT).as_posix(),
        evidence_sha256=sha256(target.read_bytes()).hexdigest(),
        source_sha256=evidence["source_sha256"],
        original_price_and_training_sources_changed=False), ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(dict(receipt=receipt.relative_to(ROOT).as_posix(), overlap_count=len(overlaps)), ensure_ascii=False))


if __name__ == "__main__":
    main()
