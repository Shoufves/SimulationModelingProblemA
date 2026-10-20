"""PR15 reproduction counterexamples, with real hash receipts and small fixtures."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import diagnose_q3_mechanisms as diagnose
import q3_scientific_equivalence as eq
import run_q3
from review_q3_diagnostics import verify_receipt

BOUNDS = dict(relative=1e-10, absolute=1e-6, currency_absolute=.01)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, allow_nan=False).encode()
    path.write_bytes(gzip.compress(raw, mtime=0) if path.name.endswith(".gz") else raw)


class ScientificEquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.reference, self.candidate = self.root / "reference", self.root / "candidate"
        self.data = dict(cash_balance_residual_cny=0., dispatch_actual_cost_cny=7404720450614.553,
                         output_mwh=12.5, year=2030, feasible=False, embedded_sha256="1" * 64,
                         projects=[dict(id="2030/coal/1", decision_year=2030, online_year=2034,
                                        status="commissioned", capacity_mw=10.)])
        self.config = dict(numerical=dict(relative_comparison_tolerance=1e-10,
            absolute_comparison_tolerance=1e-6, cash_balance_absolute_cny=.01))
        for folder in (self.reference, self.candidate):
            write(folder / "cases/policy_none.json.gz", self.data)
            write(folder / "selection_lock.json", dict(selected="none", h01_epsilon=.01))
            write(folder / "plans/plan.json", self.data["projects"])
            write(folder / "frozen_config.json", self.config)
            self.receipt(folder)
        profile = dict(reference_output="reference", reference_manifest_sha256=eq.sha(self.reference / "run_manifest.json"), tolerances=BOUNDS)
        write(self.root / "workflow/reproduction.json", profile)
        original = eq.load(self.reference / "run_manifest.json")
        self.protocol = dict(version=3, identity="Test fixture only", reproduction_protocol="workflow/reproduction.json",
            reproduction_protocol_sha256=eq.sha(self.root / "workflow/reproduction.json"),
            model_code_hashes=original["code_hashes"], input_hashes=original["input_hashes"],
            source_files={"cases/policy_none.json.gz":eq.sha(self.reference / "cases/policy_none.json.gz")})
        write(self.root / "workflow/diagnostics.json", self.protocol)
        (self.root / "scripts").mkdir()
        (self.root / "scripts/q3_scientific_equivalence.py").write_bytes(Path(eq.__file__).read_bytes())
        self.addCleanup(patch.stopall)
        patch.object(eq, "ROOT", self.root).start()
        # Admission data validation is outside this tiny fixture. All actual
        # latest-attempt, source, model and input SHA checks remain enabled.
        patch.object(run_q3, "preflight", return_value=None).start()

    def receipt(self, folder):
        value = dict(run_id=folder.name, status="conditional_experiments_completed", exit_code=0,
            config_path="workflow/q3_inputs_v5.json",
            code_hashes={"scripts/run_q3.py":eq.sha(ROOT / "scripts/run_q3.py")},
            input_hashes={"workflow/q3_inputs_v5.json":eq.sha(ROOT / "workflow/q3_inputs_v5.json")},
            outputs={p.relative_to(folder).as_posix():eq.sha(p) for p in folder.rglob("*")
                     if p.is_file() and p.name != "run_manifest.json"})
        write(folder / "run_manifest.json", value)
        write(folder.parent / (folder.name + ".latest-attempt.json"), dict(run_id=folder.name,
            output_valid_for_this_attempt=True, manifest_sha256=eq.sha(folder / "run_manifest.json")))

    def candidate_data(self, value, refresh=True):
        write(self.candidate / "cases/policy_none.json.gz", value)
        if refresh:
            self.receipt(self.candidate)

    def test_legal_roundoff_enters_diagnostic_and_binds_real_receipt(self):
        changed = deepcopy(self.data)
        changed.update(cash_balance_residual_cny=-.001953125, dispatch_actual_cost_cny=7404720450614.552)
        self.candidate_data(changed)
        out = self.root / "outputs/validation/diagnostic"
        def compute(source, target, protocol):
            write(target / "test_result.json", {"source":str(source)})
            return dict(event_probe_failures=0)
        argv = ["diagnose", "--source", str(self.candidate), "--config", "workflow/diagnostics.json",
                "--output-dir", str(out)]
        with patch.object(diagnose, "ROOT", self.root), patch.object(sys, "argv", argv), \
             patch.object(diagnose, "run_diagnostics", side_effect=compute) as solver:
            self.assertEqual(diagnose.main(), 0)
        self.assertEqual(solver.call_count, 1)
        verify_receipt(out)
        evidence = eq.load(out / "source_equivalence.json")
        self.assertEqual(evidence["numeric_differences"], 2)
        self.assertEqual(evidence["candidate"]["manifest_sha256"], eq.sha(self.candidate / "run_manifest.json"))
        self.assertNotEqual(evidence["candidate"]["output_hashes"], evidence["reference"]["output_hashes"])
        self.assertEqual(evidence["project_records"], 2)

    def test_beyond_tolerance_is_rejected_before_diagnostic(self):
        changed = deepcopy(self.data)
        changed["cash_balance_residual_cny"] = .010001
        self.candidate_data(changed)
        argv = ["diagnose", "--source", str(self.candidate), "--config", "workflow/diagnostics.json",
                "--output-dir", str(self.root / "outputs/validation/rejected")]
        with patch.object(diagnose, "ROOT", self.root), patch.object(sys, "argv", argv), \
             patch.object(diagnose, "run_diagnostics") as solver:
            with self.assertRaisesRegex(ValueError, "Scientific value differs"):
                diagnose.main()
        solver.assert_not_called()

    def test_project_identity_and_commissioning_changes_rejected(self):
        for field, value in (("id", "2030/gas/1"), ("online_year", 2035), ("status", "cancelled"), ("capacity_mw", 11.)):
            with self.subTest(field=field):
                changed = deepcopy(self.data)
                changed["projects"][0][field] = value
                self.candidate_data(changed)
                with self.assertRaises(ValueError):
                    eq.admit_source(self.candidate, self.protocol)

    def test_selection_and_small_threshold_changes_rejected(self):
        for value in (dict(selected="storage", h01_epsilon=.01), dict(selected="none", h01_epsilon=.010000000001)):
            with self.subTest(value=value):
                write(self.candidate / "selection_lock.json", value)
                self.receipt(self.candidate)
                with self.assertRaises(ValueError):
                    eq.admit_source(self.candidate, self.protocol)

    def test_hash_string_and_boolean_and_integer_type_remain_exact(self):
        for field, value in (("embedded_sha256", "1" * 63 + "2"), ("feasible", 0), ("year", 2030.), ("output_mwh", 12)):
            with self.subTest(field=field):
                changed = deepcopy(self.data)
                changed[field] = value
                self.candidate_data(changed)
                with self.assertRaises(ValueError):
                    eq.admit_source(self.candidate, self.protocol)

    def test_tampered_bytes_are_rejected_even_inside_tolerance(self):
        changed = deepcopy(self.data)
        changed["cash_balance_residual_cny"] = -.001
        self.candidate_data(changed, refresh=False)
        with self.assertRaisesRegex(Exception, "output changed"):
            eq.admit_source(self.candidate, self.protocol)

    def test_stale_latest_attempt_and_model_fingerprint_are_rejected(self):
        latest = self.candidate.parent / (self.candidate.name + ".latest-attempt.json")
        value = eq.load(latest)
        value["output_valid_for_this_attempt"] = False
        write(latest, value)
        with self.assertRaisesRegex(Exception, "Latest Q3 attempt"):
            eq.admit_source(self.candidate, self.protocol)
        self.receipt(self.candidate)
        manifest = eq.load(self.candidate / "run_manifest.json")
        manifest["code_hashes"]["scripts/run_q3.py"] = "0" * 64
        write(self.candidate / "run_manifest.json", manifest)
        value.update(output_valid_for_this_attempt=True, manifest_sha256=eq.sha(self.candidate / "run_manifest.json"))
        write(latest, value)
        with self.assertRaisesRegex(Exception, "code/input changed"):
            eq.admit_source(self.candidate, self.protocol)

    def test_non_currency_bounds_nonfinite_values_and_order(self):
        for a, b, accepted in ((0., 1e-6, True), (0., 1.01e-6, False),
                               (1e9, 1e9 + .05, True), (1e9, 1e9 + 1., False),
                               (float("nan"), float("nan"), False),
                               (["first", "second"], ["second", "first"], False)):
            with self.subTest(a=a, b=b):
                if accepted:
                    eq.compare_value(a, b, BOUNDS, eq.stats())
                else:
                    with self.assertRaises(ValueError):
                        eq.compare_value(a, b, BOUNDS, eq.stats())

    def test_structure_and_inventory_changes_are_rejected(self):
        changed = deepcopy(self.data)
        changed["projects"].append(deepcopy(changed["projects"][0]))
        self.candidate_data(changed)
        with self.assertRaisesRegex(ValueError, "list length"):
            eq.admit_source(self.candidate, self.protocol)
        self.candidate_data(self.data)
        write(self.candidate / "cases/extra.json", {})
        with self.assertRaisesRegex(ValueError, "inventory"):
            eq.admit_source(self.candidate, self.protocol)
        self.receipt(self.candidate)
        with self.assertRaisesRegex(ValueError, "inventory"):
            eq.admit_source(self.candidate, self.protocol)

    def test_frozen_reference_cannot_be_refreshed_to_match_new_source(self):
        changed = deepcopy(self.data)
        changed["output_mwh"] += 1
        write(self.reference / "cases/policy_none.json.gz", changed)
        self.receipt(self.reference)
        with self.assertRaisesRegex(ValueError, "reference manifest"):
            eq.admit_source(self.candidate, self.protocol)

    def test_duplicate_csv_columns_all_checked_and_hashes_never_numeric(self):
        a, b = self.root / "a.csv", self.root / "b.csv"
        a.write_text("year,value,value,embedded_sha256\n2030,1.0,2.0," + "1" * 64 + "\n")
        b.write_text("year,value,value,embedded_sha256\n2030,1.1,2.0," + "1" * 64 + "\n")
        with self.assertRaises(ValueError):
            eq.compare_file(a, b, BOUNDS, "test.csv")
        b.write_text(a.read_text().replace("1" * 64, "1" * 63 + "2"))
        with self.assertRaises(ValueError):
            eq.compare_file(a, b, BOUNDS, "test.csv")

    def test_diagnostic_decoded_output_tolerates_roundoff_not_metadata_hash_equality(self):
        left, right = self.root / "old_diagnostic", self.root / "new_diagnostic"
        for folder, value in ((left, 0.), (right, -.001953125)):
            write(folder / "details.json.gz", dict(cash_balance_residual_cny=value, year=2060))
            write(folder / "source_equivalence.json", dict(source=folder.name))
        manifests = [dict(outputs={p.name:eq.sha(p) for p in f.iterdir()}) for f in (left, right)]
        result = eq.compare_outputs(left, right, *manifests, BOUNDS, kind="diagnostic")
        self.assertEqual(result["file_count"], 1)
        self.assertEqual(result["numeric_differences"], 1)
        write(right / "details.json.gz", dict(cash_balance_residual_cny=1., year=2060))
        with self.assertRaises(ValueError):
            eq.compare_outputs(left, right, *manifests, BOUNDS, kind="diagnostic")

    def test_diagnostic_metadata_still_requires_its_own_raw_integrity(self):
        folder = self.root / "diagnostic_integrity"
        write(folder / "frozen_protocol.json", self.protocol)
        (folder / "diagnostic_source.py").write_text("# fixture\n")
        write(folder / "source_equivalence.json", {"source_manifest_sha256":"a" * 64})
        manifest = dict(status="diagnostics_completed", exit_code=0,
            script_sha256=eq.sha(folder / "diagnostic_source.py"),
            protocol_sha256=eq.sha(folder / "frozen_protocol.json"),
            outputs={p.name:eq.sha(p) for p in folder.iterdir()})
        write(folder / "run_manifest.json", manifest)
        verify_receipt(folder)
        write(folder / "source_equivalence.json", {"source_manifest_sha256":"b" * 64})
        with self.assertRaisesRegex(ValueError, "Changed evidence"):
            verify_receipt(folder)


if __name__ == "__main__":
    unittest.main()
