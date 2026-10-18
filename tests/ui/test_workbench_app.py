"""Run separately with the workbench environment: unittest discover -s tests/ui."""
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps/workbench.py"


def named(elements, label):
    return next(element for element in elements if element.label == label)


class WorkbenchAppTests(unittest.TestCase):
    def app(self):
        app = AppTest.from_file(str(APP), default_timeout=30).run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertFalse(app.error, str(app.error))
        return app

    def check(self, app):
        self.assertFalse(app.exception, str(app.exception))
        self.assertFalse(app.error, str(app.error))

    def test_initial_agent_results_and_synthetic_label(self):
        app = self.app()
        self.assertIn("合成机制验证", app.warning[0].value)
        self.assertEqual(app.session_state["agent_result"]["mode"], "synthetic")
        self.assertEqual(len(app.session_state["agent_result"]["cases"]), 3)
        self.assertEqual(len(app.metric), 4)

    def test_agent_parameter_submit_updates_config_and_result(self):
        app = self.app()
        before = app.session_state["agent_result"]["run_id"]
        named(app.number_input, "碳价路径系数").set_value(0)
        named(app.button, "运行主体实验").click().run()
        self.check(app)
        result = app.session_state["agent_result"]
        self.assertNotEqual(before, result["run_id"])
        self.assertTrue(all(v == 0 for v in result["configuration"]["policy"]["carbon_price_by_step"]))

    def test_agent_reset_restores_defaults_and_recomputes(self):
        app = self.app()
        original = app.session_state["agent_result"]["run_id"]
        named(app.number_input, "燃料进口能力系数").set_value(0)
        named(app.button, "运行主体实验").click().run()
        named(app.button, "恢复默认").click().run()
        self.check(app)
        self.assertEqual(app.session_state["agent_result"]["run_id"], original)
        self.assertEqual(named(app.number_input, "燃料进口能力系数").value, 1)

    def test_operations_navigation_and_empty_storage_boundary(self):
        app = self.app()
        named(app.radio, "研究工作区").set_value("连续储能实验").run()
        self.check(app)
        initial = app.session_state["operation_result"]
        self.assertAlmostEqual(initial["summaries"]["with_storage"]["unserved_mwh"], 0)
        named(app.number_input, "储能容量 MWh").set_value(0)
        named(app.button, "运行储能对照").click().run()
        self.check(app)
        result = app.session_state["operation_result"]
        self.assertEqual(result["cases"]["with_storage"]["rows"], result["cases"]["without_storage"]["rows"])

    def test_operation_window_selection_and_reset(self):
        app = self.app()
        named(app.radio, "研究工作区").set_value("连续储能实验").run()
        named(app.selectbox, "连续窗口").set_value("persistent_low_wind_solar")
        named(app.button, "运行储能对照").click().run()
        self.check(app)
        result = app.session_state["operation_result"]
        self.assertEqual(result["parameters"]["window_name"], "persistent_low_wind_solar")
        self.assertEqual(result["cases"]["with_storage"]["rows"], result["cases"]["without_storage"]["rows"])
        named(app.button, "恢复默认").click().run()
        self.check(app)
        self.assertEqual(app.session_state["operation_result"]["parameters"]["window_name"], "normal_variability")

    def test_evidence_view_rechecks_and_shows_scoped_status(self):
        app = self.app()
        named(app.radio, "研究工作区").set_value("官方数据与进度").run()
        self.check(app)
        self.assertIn("准入仅限各自用途", app.success[0].value)
        named(app.button, "重新核对").click().run()
        self.check(app)
        self.assertEqual(len(app.metric), 4)
        self.assertEqual(app.metric[1].value, "65")
        self.assertTrue(any("全国历史校准" in info.value for info in app.info))

    def test_agent_navigation_preserves_applied_controls_and_results(self):
        app = self.app()
        named(app.number_input, "碳价路径系数").set_value(0)
        named(app.button, "运行主体实验").click().run()
        run_id = app.session_state["agent_result"]["run_id"]
        named(app.radio, "研究工作区").set_value("连续储能实验").run()
        named(app.radio, "研究工作区").set_value("主体反馈实验").run()
        self.check(app)
        self.assertEqual(named(app.number_input, "碳价路径系数").value, 0)
        self.assertEqual(app.session_state["agent_result"]["run_id"], run_id)

    def test_operation_navigation_preserves_window_and_controls(self):
        app = self.app()
        named(app.radio, "研究工作区").set_value("连续储能实验").run()
        named(app.selectbox, "连续窗口").set_value("grid_bottleneck")
        named(app.number_input, "负荷系数").set_value(1.2)
        named(app.button, "运行储能对照").click().run()
        run_id = app.session_state["operation_result"]["run_id"]
        named(app.radio, "研究工作区").set_value("官方数据与进度").run()
        named(app.radio, "研究工作区").set_value("连续储能实验").run()
        self.check(app)
        self.assertEqual(named(app.selectbox, "连续窗口").value, "grid_bottleneck")
        self.assertEqual(named(app.number_input, "负荷系数").value, 1.2)
        self.assertEqual(app.session_state["operation_result"]["run_id"], run_id)

    def test_selected_mechanism_controls_metrics_and_decision_logs(self):
        app = self.app()
        for case in ("frozen_equipment", "frozen_generation_investment"):
            named(app.selectbox, "展示机制").set_value(case).run()
            self.check(app)
            result = app.session_state["agent_result"]
            self.assertEqual(app.metric[0].value, f"{result['summaries'][case]['unserved_service_su']:,.3f}")
            logs = app.dataframe[1].value.to_dict("records")
            expected = result["cases"][case]["rows"][0]["decisions"]
            self.assertEqual(len(logs), len(expected))
            self.assertEqual([log["kind"] for log in logs], [log["kind"] for log in expected])

    def test_failed_agent_submission_removes_stale_result(self):
        app = self.app()
        with patch("energy_model.workbench.run_agent_experiment", side_effect=ValueError("测试失败")):
            named(app.button, "运行主体实验").click().run()
        self.assertFalse(app.exception)
        self.assertIn("测试失败", app.error[0].value)
        self.assertNotIn("agent_result", app.session_state)
        self.assertEqual(len(app.metric), 0)
        named(app.button, "恢复默认").click().run()
        self.check(app)

    def test_failed_operation_submission_removes_stale_result(self):
        app = self.app()
        named(app.radio, "研究工作区").set_value("连续储能实验").run()
        with patch("energy_model.workbench.run_operation_experiment", side_effect=ValueError("测试失败")):
            named(app.button, "运行储能对照").click().run()
        self.assertFalse(app.exception)
        self.assertIn("测试失败", app.error[0].value)
        self.assertNotIn("operation_result", app.session_state)
        self.assertEqual(len(app.metric), 0)
        named(app.button, "恢复默认").click().run()
        self.check(app)


if __name__ == "__main__":
    unittest.main()
