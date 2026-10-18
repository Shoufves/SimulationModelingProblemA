import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from energy_model.asset_lifecycle import bind_attachments, snapshot, validate_case
from run_asset_lifecycle_case import execute
from workflow_status import read_json


class AssetLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.data = read_json(ROOT / "data/observations/qinshan_asset_permit_case.json")

    def state(self, when, **kwargs):
        return snapshot(self.data, when, evidence_cutoff="2026-10-17", **kwargs)

    def q1(self, when, **kwargs):
        return next(r for r in self.state(when, **kwargs)["units"] if r["unit_id"] == "QINSHAN-1")

    def test_seven_units_bind_three_plant_rows_without_capacity_allocation(self):
        mapped = bind_attachments(self.data, read_json(ROOT / "data/processed/attachment_assets.json"))
        self.assertEqual([len(r["unit_ids"]) for r in mapped], [1, 4, 2])
        self.assertEqual([r["original_capacity"] for r in mapped], [330, 2620, 1456])
        self.assertTrue(all(r["capacity_conversion"] is None and r["national_weight"] is None for r in mapped))
        self.assertTrue(all(u["capacity_mw"] is None for u in self.state("2024-12-31")["units"]))

    def test_renewal_updates_only_after_declared_information_date(self):
        before = self.q1("2021-09-03")
        after = self.q1("2021-09-06")
        self.assertEqual(before["latest_visible_event"]["valid_until"], "2021-07-30")
        self.assertEqual(after["latest_visible_event"]["valid_until"], "2041-07-30")
        self.assertEqual(after["permit_status"], "covered_by_recorded_end_date")

    def test_end_date_is_inclusive_and_gap_does_not_invent_retirement(self):
        self.assertEqual(self.q1("2021-07-30")["permit_status"], "covered_by_recorded_end_date")
        gap = self.q1("2021-07-31")
        self.assertEqual(gap["permit_status"], "recorded_end_passed_needs_review")
        self.assertIsNone(gap["actual_retired"])
        self.assertIsNone(gap["dispatch_available_capacity_mw"])
        self.assertEqual(self.q1("2041-07-30")["permit_status"], "covered_by_recorded_end_date")
        self.assertEqual(self.q1("2041-07-31")["permit_status"], "recorded_end_passed_needs_review")

    def test_future_event_changes_cannot_change_past(self):
        before = self.state("2020-12-31")
        self.data["permit_events"][-1]["valid_until"] = "2051-07-30"
        self.assertEqual(before, self.state("2020-12-31"))
        self.assertIsNone(self.q1("2020-12-31")["visible_lifecycle_fact"])

    def test_design_reference_is_not_a_retirement_rule(self):
        row = self.q1("2021-12-31")
        self.assertTrue(row["design_reference_reached"])
        self.assertEqual(row["permit_status"], "covered_by_recorded_end_date")
        self.assertIsNone(row["actual_retired"])

    def test_event_omission_diagnostic_changes_one_unit_and_no_physical_capacity(self):
        baseline = self.state("2021-12-31")
        omitted = self.state("2021-12-31", disabled_event_ids=["EXTENSION-2021-Q1"])
        self.assertEqual(baseline["permit_counts"]["covered_by_recorded_end_date"], 7)
        self.assertEqual(omitted["permit_counts"]["covered_by_recorded_end_date"], 6)
        self.assertIsNone(omitted["actual_retired_capacity_mw"])
        self.assertIsNone(baseline["actual_operating_capacity_mw"])

    def test_future_rows_freeze_evidence_and_never_claim_operating_status(self):
        future = self.state("2060-12-31")
        self.assertEqual(future["information_cutoff"], "2026-10-17")
        self.assertEqual(future["permit_counts"]["recorded_end_passed_needs_review"], 7)
        self.assertTrue(all(r["actual_operating_status"] is None for r in future["units"]))

    def test_missing_early_records_are_unknown_and_input_is_immutable(self):
        original = deepcopy(self.data)
        early = self.state("2015-12-31")
        self.assertEqual(early["permit_counts"], {"no_visible_permit_record": 7})
        self.assertIsNone(early["actual_operating_capacity_mw"])
        self.assertEqual(self.data, original)
        self.assertEqual(early, self.state("2015-12-31"))

    def test_invalid_duplicate_ambiguous_or_misbound_inputs_rejected(self):
        for mutation in (
            lambda d: d["units"].append(deepcopy(d["units"][0])),
            lambda d: d["permit_events"].append(deepcopy(d["permit_events"][0])),
            lambda d: d["permit_events"][-1].update(known_from="2020-01-01"),
            lambda d: d["attachment_bindings"][0]["unit_ids"].append("QINSHAN-II-1"),
            lambda d: d["units"][0].update(capacity_mw=float("nan")),
        ):
            data = deepcopy(self.data)
            mutation(data)
            with self.assertRaises(ValueError):
                validate_case(data)
        with self.assertRaises(ValueError):
            self.state("2024-12-31", disabled_event_ids=["TYPO"])

    def test_attachment_name_mismatch_rejected(self):
        attachments = read_json(ROOT / "data/processed/attachment_assets.json")
        record = next(r for r in attachments["records"] if r["record_id"] == "ATT4-NUCLEAR-R0002")
        record["name"] = "another plant"
        with self.assertRaises(ValueError):
            bind_attachments(self.data, attachments)

    def test_missing_or_tampered_admission_creates_no_output(self):
        # Copy only the evidence/config layer, then fail before touching attachment/model output.
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for path in ("workflow/asset_case.json", "workflow/model_inputs.json",
                         "workflow/source_domains.json", "data/sources.json",
                         "data/evidence_reviews.json", "data/observations/qinshan_asset_permit_case.json"):
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / path).read_bytes())
            data_path = root / "data/observations/qinshan_asset_permit_case.json"
            data_path.write_text(json.dumps(self.data) + " ", encoding="utf-8")
            with self.assertRaises(ValueError):
                execute(root)
            self.assertFalse((root / "outputs").exists())

    def test_reviewed_case_runs_reproducibly_with_case_insensitive_original_hash(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = [
                "workflow/asset_case.json", "workflow/model_inputs.json",
                "workflow/provided_inputs.json", "workflow/source_domains.json",
                "workflow/official_data_policy.md", "data/sources.json",
                "data/evidence_reviews.json", "data/observations/qinshan_asset_permit_case.json",
                "data/processed/attachment_assets.json", "附件4.xlsx",
                "scripts/run_asset_lifecycle_case.py", "scripts/workflow_status.py",
                "src/energy_model/asset_lifecycle.py",
            ]
            reviews = read_json(ROOT / "data/evidence_reviews.json")["reviews"]
            review = next(r for r in reviews if r["review_id"] == "R-QINSHAN-ASSETS-20261017")
            paths += [e["path"] for e in review["evidence_files"]]
            for path in paths:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / path).read_bytes())
            result = execute(root)
            self.assertEqual(result, execute(root))
            self.assertEqual(result["unit_count"], 7)
            self.assertEqual(result["permit_event_count"], 8)
            output = root / "outputs/asset_cases" / ("qinshan_" + result["run_id"]) / "result.json"
            output.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different result"):
                execute(root)


if __name__ == "__main__":
    unittest.main()
