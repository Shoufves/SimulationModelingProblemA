"""Admission tests use synthetic files only; no test creates a real data approval."""
import json
import sys
import shutil
import unittest
import uuid
from contextlib import contextmanager
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from workflow_status import (check_formal_inputs, check_graph, make_report,
                             official_url_allowed, sha256, source_record_sha256, write_reports)


@contextmanager
def workspace_fixture():
    parent = (ROOT / "tmp").resolve()
    parent.mkdir(exist_ok=True)
    path = parent / ("workflow-test-" + uuid.uuid4().hex)
    path.mkdir()
    try:
        yield path
    finally:
        resolved = path.resolve()
        if resolved.parent != parent or not resolved.name.startswith("workflow-test-"):
            raise ValueError("Refusing to clean a path outside the test directory")
        shutil.rmtree(resolved)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = workspace_fixture()
        self.root = self.fixture.__enter__()
        self.addCleanup(self.fixture.__exit__, None, None, None)
        self.save("data/sources.json", {"sources": [
            {"source_id": "S01", "publisher": "SYNTHETIC TEST", "title": "TEST ONLY",
             "url": "https://www.stats.gov.cn/test-only"}]})
        self.save("workflow/source_domains.json", {"domains": [{"domain": "stats.gov.cn"}]})
        self.save("data/sample.json", {
            "source_id": "S01", "columns": ["year", "value"], "rows": [[2020, 1]]})
        snapshot = self.root / "data/raw/test.txt"
        snapshot.parent.mkdir(parents=True)
        snapshot.write_text("SYNTHETIC TEST FIXTURE. NOT OFFICIAL EVIDENCE.", encoding="utf-8")
        today = date.today().isoformat()
        self.review = {
            "review_id": "TEST-ONLY", "dataset_path": "data/sample.json",
            "dataset_sha256": sha256(self.root / "data/sample.json"),
            "source_registry_sha256": sha256(self.root / "data/sources.json"),
            "status": "reviewed", "reviewer": "synthetic-test", "checked_on": today,
            "original_values_checked": True, "units_period_scope_checked": True,
            "revision_compatibility_checked": True,
            "evidence_files": [{
                "source_id": "S01", "path": "data/raw/test.txt", "sha256": sha256(snapshot),
                "official_url": "https://www.stats.gov.cn/test-only",
                "capture_kind": "official_original", "locator": "test row",
                "captured_on": today, "scope_and_units": "synthetic unit",
                "revision_note": "synthetic version", "extraction_method": "test fixture"
            }]
        }
        self.manifest = {"inputs": [{
            "dataset_path": "data/sample.json", "review_id": "TEST-ONLY", "purpose": "test only"
        }], "scenario_assumptions": []}

    def save(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def check(self):
        self.save("data/evidence_reviews.json", {"reviews": [self.review]})
        self.save("workflow/model_inputs.json", self.manifest)
        return check_formal_inputs(self.root)

    def assert_rejected(self, text):
        result = self.check()
        self.assertFalse(result["passed"])
        self.assertIn(text, "\n".join(result["errors"]))

    def test_complete_synthetic_record_passes_structural_check_only(self):
        result = self.check()
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(len(result["accepted_inputs"]), 1)
        self.assertIn("不自动验证", result["limitation"])

    def test_empty_manifest_fails(self):
        self.manifest["inputs"] = []
        self.assert_rejected("清单为空")

    def test_unknown_review_fails(self):
        self.manifest["inputs"][0]["review_id"] = "UNKNOWN"
        self.assert_rejected("找不到")

    def test_changed_dataset_fails(self):
        self.save("data/sample.json", {"source_id": "S01", "rows": [[2020, 999]]})
        self.assert_rejected("SHA256不一致")

    def test_changed_registry_requires_review_refresh(self):
        self.save("data/sources.json", {"sources": []})
        self.assert_rejected("SHA256不一致")

    def test_missing_and_tampered_snapshot_fail(self):
        path = self.root / "data/raw/test.txt"
        path.write_text("altered", encoding="utf-8")
        self.assert_rejected("SHA256不一致")
        path.unlink()
        self.assert_rejected("文件不存在")

    def test_search_snippet_cannot_be_admitted(self):
        self.review["evidence_files"][0]["capture_kind"] = "search_snippet"
        self.assert_rejected("不接受搜索摘要")

    def test_source_coverage_is_required(self):
        self.review["evidence_files"] = []
        self.assert_rejected("缺少来源证据")

    def test_all_row_sources_require_evidence(self):
        registry = {"sources": [
            {"source_id": sid, "publisher": "TEST", "title": "TEST",
             "url": "https://www.stats.gov.cn/test-only"} for sid in ("S01", "S02")]}
        self.save("data/sources.json", registry)
        self.review["source_registry_sha256"] = sha256(self.root / "data/sources.json")
        self.save("data/sample.json", {
            "columns": ["year", "value"], "rows": [[2020, 1], [2021, 2]],
            "row_sources": {"2020": "S01", "2021": "S02"}
        })
        self.review["dataset_sha256"] = sha256(self.root / "data/sample.json")
        self.assert_rejected("缺少来源证据: S02")

    def test_explicit_substantive_checks_are_required(self):
        self.review["original_values_checked"] = "true"
        self.assert_rejected("未完成实质检查")

    def test_official_url_must_match_registry(self):
        self.review["evidence_files"][0]["official_url"] = "https://www.stats.gov.cn/other"
        self.assert_rejected("网址与来源登记不一致")

    def test_outside_workspace_evidence_rejected(self):
        self.review["evidence_files"][0]["path"] = "../outside.txt"
        self.assert_rejected("必须位于工作区内")

    def test_spoofed_domains_rejected(self):
        for url in ("https://stats.gov.cn.evil.example/a",
                    "https://evil-stats.gov.cn/a",
                    "https://stats.gov.cn@evil.example/a",
                    "https://evil.example@stats.gov.cn/a",
                    "file://stats.gov.cn/a", "https://stats.gov.cn:999/a"):
            with self.subTest(url=url):
                self.assertFalse(official_url_allowed(url, ["stats.gov.cn"]))
        self.assertTrue(official_url_allowed("https://www.stats.gov.cn/a", ["stats.gov.cn"]))

    def test_duplicate_reviews_fail(self):
        self.check()
        self.save("data/evidence_reviews.json", {"reviews": [self.review, self.review]})
        self.assertFalse(check_formal_inputs(self.root)["passed"])

    def test_source_scoped_hash_allows_unrelated_addition_but_rejects_used_change(self):
        registry = json.loads((self.root / "data/sources.json").read_text(encoding="utf-8"))
        self.review["source_records_sha256"] = {
            "S01": source_record_sha256(registry["sources"][0])}
        registry["sources"].append({"source_id": "S02", "title": "UNRELATED SYNTHETIC"})
        self.save("data/sources.json", registry)
        self.assertTrue(self.check()["passed"])
        registry["sources"][0]["title"] = "ALTERED REFERENCED SOURCE"
        self.save("data/sources.json", registry)
        self.assert_rejected("SHA256不一致")

    def test_source_scoped_hash_requires_complete_coverage(self):
        for mapping in ({}, {"S02": "0" * 64}):
            self.review["source_records_sha256"] = mapping
            self.assert_rejected("恰好覆盖")

    def test_module_scope_preserves_global_audit_and_checks_missing_or_duplicate(self):
        self.manifest["inputs"].append({
            "dataset_path": "data/unrelated.json", "review_id": "MISSING", "purpose": "TEST"})
        self.assertFalse(self.check()["passed"])
        selected = {"data/sample.json"}
        self.assertTrue(check_formal_inputs(self.root, selected)["passed"])
        self.assertFalse(check_formal_inputs(self.root, {"data/not_declared.json"})["passed"])
        self.manifest["inputs"].append(self.manifest["inputs"][0])
        self.check()
        self.assertFalse(check_formal_inputs(self.root, selected)["passed"])


class WorkflowTests(unittest.TestCase):
    def test_dependency_cycles_and_unknown_ids_fail(self):
        self.assertTrue(check_graph([
            {"id": "A", "depends_on": ["B"]}, {"id": "B", "depends_on": ["A"]}]))
        self.assertTrue(check_graph([{"id": "A", "depends_on": ["MISSING"]}]))
        self.assertEqual(check_graph([
            {"id": "A", "depends_on": []}, {"id": "B", "depends_on": ["A"]}]), [])

    def test_current_workspace_integrity(self):
        report = make_report(ROOT)
        self.assertTrue(report["workflow_check"]["passed"],
                        report["workflow_check"]["errors"])
        self.assertEqual(len(report["workflow_check"]["original_inputs"]), 5)
        self.assertGreater(report["measurement_count"], 0)

    def test_selected_prompt_does_not_change_current_stage(self):
        state_hash = sha256(ROOT / "workflow/state.json")
        report = make_report(ROOT, "W4")
        self.assertEqual(sha256(ROOT / "workflow/state.json"), state_hash)
        self.assertEqual(report["selected_stage"], "W4")
        report["pending_dependencies"] = ["W1", "W2"]
        with workspace_fixture() as root:
            (root / "prompts").mkdir()
            for name in ("00_master.md", "05_agent_model.md"):
                (root / "prompts" / name).write_text(
                    (ROOT / "prompts" / name).read_text(encoding="utf-8"), encoding="utf-8")
            write_reports(root, report)
            prompt = (root / "outputs/workflow/next_prompt.md").read_text(encoding="utf-8")
            self.assertIn("# A题总控提示词", prompt)
            self.assertIn("# W4 多智能体模型实现", prompt)
            self.assertIn("本阶段尚有正式验收依赖：W1、W2", prompt)


if __name__ == "__main__":
    unittest.main()
