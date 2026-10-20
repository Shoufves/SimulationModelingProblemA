"""Reject selection leakage, missing candidates and fabricated search receipts."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
AVAILABLE = all(importlib.util.find_spec(x) for x in ("mesa", "scipy", "pdfplumber"))
if AVAILABLE:
    from review_q2_joint_search import audit_sequence


@unittest.skipUnless(AVAILABLE, "Install research dependencies")
class JointSearchAuditTests(unittest.TestCase):
    def fixture(self):
        config = dict(authority_scenarios=[5], training_years=[2015, 2016], blocks=[{"p": [0, 1, 2]}])
        warm = {"5": {"parameters": {"p": 0}}}
        trials = [dict(index=i, authority=5, parameters={"p": i}, loss=score, status="success",
                       paths=[dict(year=2015), dict(year=2016)]) for i, score in enumerate([3, 1, 1])]
        stages = [dict(stage=0, block=None, count=1, best={"5": dict(index=0, loss=3)}),
                  dict(stage=1, block=config["blocks"][0], count=3, best={"5": dict(index=1, loss=1)})]
        return config, warm, trials, stages

    def test_first_equal_training_score_wins_and_warm_start_is_not_repeated(self):
        self.assertEqual(audit_sequence(*self.fixture())[5]["index"], 1)

    def test_eval_year_in_training_receipt_rejected(self):
        args = list(self.fixture())
        args[2][1]["paths"].append(dict(year=2022))
        with self.assertRaisesRegex(ValueError, "non-training"):
            audit_sequence(*args)

    def test_later_equal_score_chosen_for_better_eval_is_rejected(self):
        args = list(self.fixture())
        args[3][1]["best"]["5"]["index"] = 2
        with self.assertRaisesRegex(ValueError, "winner"):
            audit_sequence(*args)

    def test_missing_or_replaced_candidate_rejected(self):
        args = list(self.fixture())
        args[2].pop()
        with self.assertRaisesRegex(ValueError, "Missing declared"):
            audit_sequence(*args)
        args = list(self.fixture())
        args[2][2]["parameters"]["p"] = 3
        with self.assertRaisesRegex(ValueError, "Candidate order"):
            audit_sequence(*args)

    def test_failed_trial_is_retained_but_cannot_win(self):
        args = list(self.fixture())
        args[2][1].update(status="failed", loss=None, error="physical infeasibility")
        args[3][1]["best"]["5"] = dict(index=2, loss=1)
        self.assertEqual(audit_sequence(*args)[5]["index"], 2)

    def test_undeclared_extra_trial_and_nonfinite_loss_rejected(self):
        args = list(self.fixture())
        args[2].append(deepcopy(args[2][-1]))
        with self.assertRaisesRegex(ValueError, "Undeclared"):
            audit_sequence(*args)
        args = list(self.fixture())
        args[2][1]["loss"] = float("nan")
        with self.assertRaisesRegex(ValueError, "Invalid training"):
            audit_sequence(*args)


if __name__ == "__main__":
    unittest.main()
