"""Synthetic temporary fixtures only; these tests cannot approve national data."""
import json
import shutil
import sys
import tempfile
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_demand_hindcast import CONFIG, DATASETS, calculate, execute, load_history
from workflow_status import sha256


def write(root, path, value):
    destination = root / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def fixture(root):
    """Build explicitly artificial evidence in an isolated temporary directory."""
    config = json.loads((ROOT / CONFIG).read_text(encoding="utf-8"))
    write(root, CONFIG, config)
    write(root, "workflow/source_domains.json", {"domains": [{"domain": "stats.gov.cn"}]})
    sources = [{"source_id": sid, "url": f"https://www.stats.gov.cn/TEST_ONLY/{sid}",
                "publisher": "TEST FIXTURE", "title": "SYNTHETIC, NOT OFFICIAL EVIDENCE"}
               for _, sid in DATASETS.values()]
    write(root, "data/sources.json", {"sources": sources})
    reviews, inputs = [], []
    for key, (path, sid) in DATASETS.items():
        energy = key == "energy_dataset"
        table = {"source_id": sid, "locator": "SYNTHETIC TEST ONLY",
                 "columns": ["year", "total_energy_consumption" if energy else "real_gdp_growth_pct"],
                 "rows": [[year, 10000 * 1.03 ** (year - 2015) if energy else 5]
                          for year in range(2015, 2025)]}
        table.update({"total_unit": "万吨标准煤"} if energy else {"unit": "%"})
        write(root, path, table)
        evidence_path = f"data/raw/official/TEST_ONLY_{sid}.txt"
        evidence = root / evidence_path
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text("SYNTHETIC TEST FIXTURE; NEVER REAL EVIDENCE", encoding="utf-8")
        review_id = f"TEST_ONLY_{sid}"
        reviews.append({
            "review_id": review_id, "dataset_path": path, "dataset_sha256": sha256(root / path),
            "source_registry_sha256": sha256(root / "data/sources.json"),
            "status": "reviewed", "reviewer": "SYNTHETIC TEST FIXTURE",
            "checked_on": date.today().isoformat(), "original_values_checked": True,
            "units_period_scope_checked": True, "revision_compatibility_checked": True,
            "evidence_files": [{
                "source_id": sid, "path": evidence_path, "sha256": sha256(evidence),
                "official_url": next(s["url"] for s in sources if s["source_id"] == sid),
                "capture_kind": "official_page_capture", "locator": "SYNTHETIC TEST ONLY",
                "captured_on": date.today().isoformat(), "scope_and_units": "TEST",
                "revision_note": "TEST", "extraction_method": "SYNTHETIC FIXTURE",
            }],
        })
        inputs.append({"dataset_path": path, "review_id": review_id, "purpose": "TEST ONLY"})
    write(root, "data/evidence_reviews.json", {"reviews": reviews})
    write(root, "workflow/model_inputs.json", {"inputs": inputs})
    for name in ["scripts/run_demand_hindcast.py", "scripts/build_foundation.py",
                 "scripts/workflow_status.py", "src/energy_model/baselines.py",
                 "workflow/official_data_policy.md"]:
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    return config


class DemandHindcastTests(unittest.TestCase):
    def test_missing_admission_creates_no_calibration_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            write(root, "workflow/model_inputs.json", {"inputs": []})
            code, report = execute(root)
            self.assertEqual(code, 2)
            self.assertEqual(len(report["accepted_bindings"]), 0)
            self.assertFalse((root / "outputs/calibration").exists())

    def test_changed_observation_is_rejected_by_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            path = DATASETS["energy_dataset"][0]
            table = json.loads((root / path).read_text(encoding="utf-8"))
            table["rows"][-1][-1] *= 2
            write(root, path, table)
            code, report = execute(root)
            self.assertEqual(code, 2)
            self.assertTrue(any("SHA256" in error for error in report["blocked_for"]))
            self.assertFalse((root / "outputs/calibration").exists())

    def test_units_checked_even_with_structurally_valid_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            path = DATASETS["energy_dataset"][0]
            table = json.loads((root / path).read_text(encoding="utf-8"))
            table["total_unit"] = "亿吨标准煤"
            write(root, path, table)
            reviews = json.loads((root / "data/evidence_reviews.json").read_text(encoding="utf-8"))
            reviews["reviews"][0]["dataset_sha256"] = sha256(root / path)
            write(root, "data/evidence_reviews.json", reviews)
            code, report = execute(root)
            self.assertEqual(code, 2)
            self.assertEqual(report["ready_for"], [])
            self.assertTrue(any("原单位" in error for error in report["blocked_for"]))

    def test_holdout_energy_does_not_affect_fit_or_predictions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root)
            history = load_history(root, config)
            changed = deepcopy(history)
            for row in changed:
                if row["year"] >= 2022:
                    row["energy_mtce"] *= 10
            original, altered = calculate(history, config), calculate(changed, config)
            self.assertEqual(original["fitted"], altered["fitted"])
            self.assertEqual([row["predictions_mtce"] for row in original["evaluation"]["rows"]],
                             [row["predictions_mtce"] for row in altered["evaluation"]["rows"]])
            self.assertNotEqual(original["evaluation"]["metrics"], altered["evaluation"]["metrics"])

    def test_check_only_has_no_results_and_excludes_2025(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root)
            code, _ = execute(root, check_only=True)
            self.assertEqual(code, 0)
            self.assertFalse((root / "outputs/calibration").exists())
            self.assertEqual([r["year"] for r in load_history(root, config)], list(range(2015, 2025)))

    def test_success_is_reproducible_with_evidence_and_yearly_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            code, artifact = execute(root)
            self.assertEqual(code, 0)
            result = json.loads(Path(artifact["result"]).read_text(encoding="utf-8"))
            self.assertEqual(len(result["training_rows"]), 7)
            self.assertEqual(len(result["evaluation"]["rows"]), 3)
            self.assertEqual(len(result["evaluation"]["metrics"]), 4)
            self.assertIn("data/raw/official/TEST_ONLY_S01.txt", result["provenance"]["sha256"])
            self.assertEqual(execute(root)[1], artifact)
            for row in result["evaluation"]["rows"]:
                for error in row["errors"].values():
                    self.assertGreaterEqual(error["absolute_mtce"], 0)
                    self.assertAlmostEqual(error["absolute_pct"],
                                           error["absolute_mtce"] / row["actual_energy_mtce"] * 100)

    def test_changed_evaluation_design_fails_before_calculation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root)
            config["evaluation_years"] = [2024]
            write(root, CONFIG, config)
            with self.assertRaisesRegex(ValueError, "研究方案"):
                execute(root)
            self.assertFalse((root / "outputs/calibration").exists())

    def test_explicitly_configured_and_reviewed_alternative_path_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root)
            old = config["energy_dataset"]
            replacement = "data/observations/TEST_ONLY_alternative_energy.json"
            write(root, replacement, json.loads((root / old).read_text(encoding="utf-8")))
            config["energy_dataset"] = replacement
            write(root, CONFIG, config)
            reviews = json.loads((root / "data/evidence_reviews.json").read_text(encoding="utf-8"))
            reviews["reviews"][0]["dataset_path"] = replacement
            reviews["reviews"][0]["dataset_sha256"] = sha256(root / replacement)
            write(root, "data/evidence_reviews.json", reviews)
            manifest = json.loads((root / "workflow/model_inputs.json").read_text(encoding="utf-8"))
            manifest["inputs"][0]["dataset_path"] = replacement
            write(root, "workflow/model_inputs.json", manifest)
            code, artifact = execute(root)
            self.assertEqual(code, 0)
            result = json.loads(Path(artifact["result"]).read_text(encoding="utf-8"))
            self.assertIn(replacement, result["provenance"]["sha256"])
            self.assertNotIn(old, result["provenance"]["sha256"])

    def test_unrelated_unreviewed_input_does_not_block_this_module(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            manifest = json.loads((root / "workflow/model_inputs.json").read_text(encoding="utf-8"))
            manifest["inputs"].append({"dataset_path": "data/observations/TEST_ONLY_unrelated.json",
                                       "review_id": "MISSING", "purpose": "SYNTHETIC unrelated"})
            write(root, "workflow/model_inputs.json", manifest)
            self.assertEqual(execute(root, check_only=True)[0], 0)

    def test_configured_source_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = fixture(root)
            config["required_source_ids"]["energy_dataset"] = "S06"
            write(root, CONFIG, config)
            code, report = execute(root)
            self.assertEqual(code, 2)
            self.assertTrue(any("来源版本" in error for error in report["blocked_for"]))
            self.assertFalse((root / "outputs/calibration").exists())
