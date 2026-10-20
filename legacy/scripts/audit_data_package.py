"""Audit the saved round-one package without downloads or model execution."""

import ast
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CAT = DATA / "catalog"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load(name):
    return json.loads((CAT / name).read_text(encoding="utf-8"))


def main():
    checks = []
    hashes = {}

    def verify(name, passed, detail=""):
        checks.append(dict(check=name, passed=bool(passed), detail=detail))

    sources = load("sources.json")
    manifest = {x["id"]: x for x in load("retrieval_manifest.json")}
    inventory = pd.read_csv(CAT / "dataset_inventory.csv")
    verify("unique_source_ids", len({x["id"] for x in sources}) == len(sources))
    verify("unique_source_paths", len({x["path"] for x in sources}) == len(sources))
    archived = set()
    failures = []
    for source in sources:
        path = (DATA / source["path"]).resolve()
        verify("contained_" + source["id"], path.is_relative_to(DATA.resolve()))
        entry = manifest.get(source["id"], {})
        verify("manifest_" + source["id"],
               entry.get("path") == source["path"] and entry.get("url") == source["url"])
        if not path.exists():
            failures.append(source["id"])
            verify("failed_retrieval_explained_" + source["id"],
                   entry.get("status") == "download_failed" and bool(entry.get("error")))
            continue
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        hashes[source["path"]] = digest
        archived.add(path)
        verify("raw_digest_and_size_" + source["id"],
               digest == entry.get("sha256") and len(payload) == entry.get("bytes"))
        verify("retrieval_timestamp_" + source["id"],
               datetime.fromisoformat(entry["retrieved_at"]).utcoffset() is not None)
        if source["format"] in {"pdf", "xlsx"}:
            verify("file_signature_" + source["id"],
                   payload.startswith(b"%PDF" if source["format"] == "pdf" else b"PK"))
    # This is the original yx package audit. Other source namespaces now share
    # data/raw and are covered by the unified catalog and workspace audit.
    yx_raw_roots = [DATA / "raw" / name for name in
                    ("batch1_national", "batch2_mechanisms", "batch3_scenarios")]
    verify("all_yx_raw_files_registered",
           archived == {p.resolve() for folder in yx_raw_roots
                        for p in folder.rglob("*") if p.is_file()})
    verify("all_processed_files_registered",
           set(inventory.dataset) == {p.name for p in (DATA / "processed").glob("*.csv")})
    for row in inventory.itertuples(index=False):
        path = DATA / row.path
        frame = pd.read_csv(path)
        verify("processed_shape_" + row.dataset, frame.shape == (row.rows, row.columns))
        verify("processed_source_scope_" + row.dataset,
               all((DATA / s["path"]).exists() for s in sources
                   if s["id"] in row.source_ids.split(";")))
        hashes[row.path] = hashlib.sha256(path.read_bytes()).hexdigest()
    price = pd.read_csv(DATA / "processed/commodity_price_references.csv")
    candidate = price[price.source_id.eq("WB_PINK_SHEET_ANNUAL")]
    verify("candidate_prices_quarantined",
           len(candidate) > 0 and candidate.status.eq("quarantined_version_check").all())
    transmission = pd.read_csv(DATA / "processed/transmission_lines_candidate.csv")
    verify("candidate_transmission_quarantined",
           transmission.status.eq("quarantined_type_and_year_crosscheck").all())
    load_frame = pd.read_csv(DATA / "processed/province_load_2018_MWh.csv")
    verify("hourly_shape_and_unique_time",
           load_frame.shape == (8760, 33) and load_frame.timestamp_UTC_plus_08.is_unique)
    coverage = pd.read_csv(CAT / "annual_coverage.csv")
    common = [int(y) for y, part in coverage.groupby("year") if part.available.all()]
    verify("national_common_window", list(range(2014, 2025)) == common)
    support = load("support_and_gap_matrix.json")
    verify("twelve_support_records", len(support["assumptions"]) == 12)
    verify("sixteen_decided_gaps",
           len(support["gaps"]) == 16 and all(x["decision"] and x["next_evidence"]
                                             and x["claim_limit"] for x in support["gaps"]))
    quality = load("data_quality_checks.json")
    verify("preparation_error_count_zero", quality["error_count"] == 0)
    verify("catalog_counts_match",
           quality["source_file_count"] == len(archived)
           and quality["failed_download_count"] == len(failures)
           and quality["processed_dataset_count"] == len(inventory))
    for path in (ROOT / "scripts").glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    verify("purpose_scripts_are_centralized",
           not list(DATA.rglob("*.py"))
           and not list((ROOT / "docs/design").glob("*.py")))
    document = ROOT / "docs/design/A题内容分析与数据准备清单.md"
    text = document.read_text(encoding="utf-8")
    verify("master_document_round_and_scope",
           "第5轮" in text and "## 14." in text and "2014-2024" in text
           and all(x["id"] in text for x in support["assumptions"] + support["gaps"]))
    hashes[str(document.relative_to(ROOT))] = hashlib.sha256(document.read_bytes()).hexdigest()
    error_count = sum(not x["passed"] for x in checks)
    result = dict(
        audited_at=datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        source_files=len(archived), registered_sources=len(sources),
        failed_retrieval_ids=failures, processed_tables=len(inventory),
        national_common_window=common, candidate_national_baseline=2024,
        detailed_balance_checkpoint=2023, latest_partial_crosscheck=2025,
        support_records=12, decided_gaps=16, checks=checks, error_count=error_count,
        unresolved_quality_warnings=[x for x in quality["checks"]
                                     if x["severity"] == "warning" and not x["passed"]],
        sha256=hashes,
        acceptance_scope="First-round data preparation; does not assert model readiness, independent validation, or complete data.",
        model_not_executed=True,
    )
    (CAT / "package_audit.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in {"checks", "sha256"}},
                     ensure_ascii=False, indent=2))
    if error_count:
        for item in checks:
            if not item["passed"]:
                print(item)
        raise SystemExit("Package audit failed.")


if __name__ == "__main__":
    main()
