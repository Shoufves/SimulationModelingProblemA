import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_attachments import extract, explicit_province, formula_kw, tag_duplicates


class AttachmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records, cls.sheets, cls.auxiliary, cls.groups, cls.reviews = extract()
        cls.by_id = {r["record_id"]: r for r in cls.records}

    def test_all_named_rows_retained_and_stable_ids(self):
        self.assertEqual(len(self.records), 890)
        self.assertEqual(len(self.by_id), 890)
        self.assertEqual([s["named_records"] for s in self.sheets], [633, 193, 31, 16, 17])
        self.assertEqual(sum(len(s["ignored_blank_name_rows"]) for s in self.sheets), 546)

    def test_formula_not_executed_arbitrarily(self):
        self.assertEqual(formula_kw(5000, "=B2*10^3", 2), 5000000)
        for expression in ("=B3*10^3", "=HYPERLINK(\"evil\")", "=B2*1000", "__import__('os')"):
            self.assertIsNone(formula_kw(5000, expression, 2))
        thermal = [r for r in self.records if r["technology"] == "thermal"]
        self.assertTrue(all(r["kw_recomputed"] == r["kw_cached_value"] for r in thermal))

    def test_unknown_units_dates_and_fuel_not_invented(self):
        self.assertTrue(all(r["year"] is None and r["operating_status"] is None for r in self.records))
        self.assertTrue(all(not r["national_calibration_eligible"] for r in self.records))
        self.assertIsNone(self.by_id["ATT3-WIND-R0002"]["capacity_mw_from_declared_kw"])
        self.assertIn("thermal_fuel_unresolved", self.by_id["ATT1-THERMAL-R0002"]["issues"])

    def test_duplicates_kept_and_conflicts_distinguished(self):
        self.assertEqual(len(self.groups), 9)
        kinds = {g["name"]: g["kind"] for g in self.groups}
        self.assertEqual(kinds["金山电厂"], "same_name_conflicting_fields")
        self.assertEqual(kinds["唐山北郊电厂"], "same_name_same_capacity_location")
        self.assertEqual(kinds["天桥水电站"], "same_name_conflicting_fields")

    def test_province_requires_explicit_evidence(self):
        self.assertIsNone(explicit_province("海盐县"))
        self.assertIsNone(explicit_province("三道河子镇"))
        self.assertEqual(explicit_province("浙江北仑"), "浙江省")
        self.assertEqual(explicit_province("内蒙古"), "内蒙古自治区")
        self.assertEqual(self.by_id["ATT2-PUMP-R0008"]["original_province"], "辽宁省")
        self.assertEqual(self.by_id["ATT2-PUMP-R0008"]["province"], "黑龙江省")
        for rid in ("ATT2-PUMP-R0028", "ATT2-PUMP-R0029"):
            self.assertEqual(self.by_id[rid]["province"], "河北省")

    def test_coordinates_quarantined_without_erasing_originals(self):
        r = self.by_id["ATT2-PUMP-R0008"]
        self.assertIsNone(r["coordinates"])
        self.assertEqual(r["original_coordinates"]["longitude"], 119.077)
        self.assertIsNone(r["coordinate_reference_system"])

    def test_approval_capacity_not_promoted_to_operating_capacity(self):
        r = self.by_id["ATT2-PUMP-R0008"]
        self.assertEqual(r["official_capacity_reference"]["value_mw"], 1200)
        self.assertEqual(r["official_capacity_reference"]["status"], "approved_project_capacity")
        self.assertIsNone(r["operating_status"])
        self.assertEqual(self.by_id["ATT2-HYDRO-R0172"]["official_capacity_reference"]["value_mw"], 22500)

    def test_auxiliary_total_does_not_become_a_project(self):
        auxiliary = next(x for x in self.auxiliary if x["source_file"] == "附件2.xlsx")
        self.assertEqual(auxiliary["value"], "=SUM(B2:B194)*1000")
        self.assertFalse(any(r["original_capacity"] == 203235500 for r in self.records))


if __name__ == "__main__":
    unittest.main()
