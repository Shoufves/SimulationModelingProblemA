"""Local research interface; all simulations remain explicitly synthetic."""
import json
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from energy_model.workbench import (
    AGENT_DEFAULTS, AGENT_LABELS, OPERATION_DEFAULTS, OPERATION_LABELS, WINDOW_LABELS,
    read_observation, run_agent_experiment, run_operation_experiment, workspace_snapshot,
)

TEAL, GOLD, RED, BLUE, GRAY = "#087f73", "#bb871b", "#ce4b4b", "#467ab4", "#738088"
TECHNOLOGY_LABELS = {"hydro": "水电", "nuclear": "核电", "wind": "风电",
                     "solar": "光伏", "coal": "煤电", "gas": "气电", "renewable": "可再生"}
TECHNOLOGY_COLORS = [BLUE, "#9a70a9", TEAL, GOLD, GRAY, "#d37a49"]

st.set_page_config(page_title="多能源仿真实验台 · A题", page_icon=":material/hub:",
                   layout="wide", initial_sidebar_state="auto")
st.markdown("""
<style>
.block-container { padding-top: 1.7rem; padding-bottom: 2rem; max-width: 1540px; }
h1 { font-size: 1.65rem !important; font-weight: 650 !important; }
h2 { font-size: 1.2rem !important; }
h3 { font-size: 1.05rem !important; }
[data-testid="stMetricValue"] { font-size: 1.75rem; }
[data-testid="stSidebar"] { border-right: 1px solid #e3e8e9; }
[data-testid="stSidebar"] .block-container { padding-top: 1rem; }
.stButton button, .stDownloadButton button { border-radius: 6px; }
</style>
""", unsafe_allow_html=True)


def reset_controls(prefix, defaults, result_key):
    st.session_state[prefix + "saved_controls"] = dict(defaults)
    for name, value in defaults.items():
        st.session_state[prefix + name] = value
    if prefix == "ops_":
        st.session_state["ops_window_name"] = "normal_variability"
        st.session_state[prefix + "saved_controls"]["window_name"] = "normal_variability"
    st.session_state.pop(result_key, None)


def number(label, prefix, name, defaults, low, high, step, help_text=None):
    key = prefix + name
    if key not in st.session_state:
        st.session_state[key] = st.session_state.get(prefix + "saved_controls", defaults)[name]
    return st.number_input(label, min_value=float(low), max_value=float(high), step=float(step),
                           key=key, help=help_text)


def download_record(record):
    st.caption(f"运行标识 {record['run_id']} · {record['created_at']}")
    st.download_button(
        "下载本次实验", data=json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False),
        file_name=f"synthetic_{record['kind']}_{record['run_id']}.json",
        mime="application/json", icon=":material/download:", key="download_" + record["kind"],
    )
    st.json({"参数": record["parameters"], "配置校验值": record["configuration_sha256"],
             "代码校验值": record["implementation_sha256"]}, expanded=True)
    with st.expander("完整合成配置"):
        st.json(record["configuration"])


def synthetic_header(title, scope):
    st.title(title)
    st.caption(scope)
    st.warning("合成机制验证 · 全国历史校准、2030/2060预测尚未完成。", icon=":material/science:")


def year_label(years):
    if len(years) > 1 and years == list(range(years[0], years[-1] + 1)):
        return f"{years[0]}–{years[-1]}（{len(years)}年）"
    return "、".join(map(str, years))


def agents_view():
    with st.sidebar:
        st.divider()
        st.subheader("实验参数")
        st.caption("修改参数后点击运行；页面结果和导出使用上次成功运行的参数。")
        st.button("恢复默认", on_click=reset_controls,
                  args=("agent_", AGENT_DEFAULTS, "agent_result"), icon=":material/restart_alt:",
                  key="reset_agents")
        with st.form("agent_parameters"):
            values = {
                "carbon_multiplier": number("碳价路径系数", "agent_", "carbon_multiplier",
                                           AGENT_DEFAULTS, 0, 3, 0.1, "合成碳价路径的倍数；1为原配置，0关闭碳价。"),
                "renewable_capex_multiplier": number("可再生投资成本系数", "agent_", "renewable_capex_multiplier",
                                                     AGENT_DEFAULTS, 0.25, 2.5, 0.05, "可再生发电单位投资成本的倍数。"),
                "import_capacity_multiplier": number("燃料进口能力系数", "agent_", "import_capacity_multiplier",
                                                     AGENT_DEFAULTS, 0, 1.5, 0.1, "各燃料进口上限的倍数；0关闭燃料进口。"),
                "grid_capacity_multiplier": number("送出能力系数", "agent_", "grid_capacity_multiplier",
                                                   AGENT_DEFAULTS, 0.1, 1.5, 0.1, "发电侧送出上限的倍数；数值越小约束越强。"),
            }
            submitted = st.form_submit_button("运行主体实验", type="primary", icon=":material/play_arrow:",
                                             width="stretch")
    if submitted or "agent_result" not in st.session_state:
        st.session_state["agent_saved_controls"] = dict(values)
        st.session_state.pop("agent_result", None)
        with st.spinner("计算主体决策与机制对照"):
            st.session_state["agent_result"] = run_agent_experiment(values)
    record = st.session_state["agent_result"]
    synthetic_header("主体反馈实验", "抽象决策步 1–8 · 能量 EU / 服务 SU / 货币 CU")
    p = record["parameters"]
    st.caption(f"结果所用参数：碳价 {p['carbon_multiplier']:g} · 可再生投资成本 {p['renewable_capex_multiplier']:g}"
               f" · 燃料进口能力 {p['import_capacity_multiplier']:g} · 送出能力 {p['grid_capacity_multiplier']:g}")
    case = st.selectbox("展示机制", list(AGENT_LABELS), format_func=AGENT_LABELS.get, key="agent_case",
                        help="同步切换顶部指标、系统轨迹和主体决策；机制对照与导出包含全部三组。")
    s = record["summaries"][case]
    for col, label, value in zip(st.columns(4),
                                ("累计缺供 SU", "合成燃烧排放", "设备投资 CU", "发电投资 CU"),
                                (s["unserved_service_su"], s["synthetic_emissions"],
                                 s["equipment_investment_cu"], s["generation_investment_cu"])):
        col.metric(label, f"{value:,.3f}")
    st.caption(f"{AGENT_LABELS[case]} · 最大守恒残差 {s['max_abs_balance_residual_eu']:.2e} EU"
               f" · 期末在建容量 {s['pending_capacity_units']:.2f} 抽象单位"
               f" · 运行 {record['run_id']}")
    paths, comparison, decisions, export = st.tabs(
        ["系统轨迹", "机制对照", "主体决策", "配置与导出"], key="agent_tabs")
    with paths:
        rows = record["cases"][case]["rows"]
        capacities = pd.DataFrame([{"步": r["step"], **{
            TECHNOLOGY_LABELS[k]: v for k, v in r["capacity_at_start"].items()}} for r in rows])
        shares = pd.DataFrame([{"步": r["step"],
                               "工业": r["services"]["industry"]["electric_share"] * 100,
                               "交通": r["services"]["transport"]["electric_share"] * 100} for r in rows])
        left, right = st.columns(2)
        with left:
            st.subheader("期初可用容量 · 抽象单位")
            st.area_chart(capacities, x="步", y=["煤电", "气电", "可再生"], color=[GRAY, GOLD, TEAL],
                          stack=True, height=250)
        with right:
            st.subheader("电气设备份额 · %")
            st.line_chart(shares, x="步", y=["工业", "交通"], color=[TEAL, BLUE], height=250)
        trajectory = pd.DataFrame([{
            "步": r["step"], "未满足服务 SU": sum(v["unserved_service"] for v in r["services"].values()),
            "交付电价 CU/EU": r["electricity_price_delivered"],
        } for r in rows])
        left, right = st.columns(2)
        with left:
            st.subheader("未满足服务 · SU")
            st.bar_chart(trajectory, x="步", y="未满足服务 SU", color=RED, height=180)
        with right:
            st.subheader("交付电价 · CU/EU")
            st.line_chart(trajectory, x="步", y="交付电价 CU/EU", color=BLUE, height=180)
    with comparison:
        table = pd.DataFrame([{
            "机制": AGENT_LABELS[name], "缺供 SU": item["unserved_service_su"],
            "合成燃烧排放": item["synthetic_emissions"], "设备投资 CU": item["equipment_investment_cu"],
            "发电投资 CU": item["generation_investment_cu"],
            "守恒残差 EU": item["max_abs_balance_residual_eu"],
        } for name, item in record["summaries"].items()])
        st.dataframe(table, hide_index=True, width="stretch")
        left, right = st.columns(2)
        with left:
            st.subheader("累计缺供 · SU")
            st.bar_chart(table, x="机制", y="缺供 SU", color=RED)
        with right:
            st.subheader("合成燃烧排放")
            st.bar_chart(table, x="机制", y="合成燃烧排放", color=TEAL)
        st.caption("三组机制对照不计作赛题的全国基准及至少三种正式情景。")
    with decisions:
        case_rows = record["cases"][case]["rows"]
        index = st.select_slider("决策步", options=[row["step"] for row in case_rows])
        row = next(row for row in case_rows if row["step"] == index)
        actor = st.selectbox("主体", ["全部主体"] + sorted({d["actor"] for d in row["decisions"]}))
        logs = [d for d in row["decisions"] if actor == "全部主体" or d["actor"] == actor]
        st.caption(f"{AGENT_LABELS[case]} · 信息截止步、预算、净现值、下单及投运时间均来自本次实际决策日志。")
        st.dataframe(pd.DataFrame(logs).dropna(axis=1, how="all"), hide_index=True, width="stretch")
    with export:
        download_record(record)


def operations_view():
    with st.sidebar:
        st.divider()
        st.subheader("窗口参数")
        st.caption("修改参数后点击运行；切换工作区保留已运行参数。")
        st.button("恢复默认", on_click=reset_controls,
                  args=("ops_", OPERATION_DEFAULTS, "operation_result"), icon=":material/restart_alt:",
                  key="reset_operations")
        with st.form("operation_parameters"):
            if "ops_window_name" not in st.session_state:
                st.session_state["ops_window_name"] = st.session_state.get(
                    "ops_saved_controls", {}).get("window_name", "normal_variability")
            window = st.selectbox("连续窗口", list(WINDOW_LABELS), format_func=WINDOW_LABELS.get,
                                  key="ops_window_name")
            values = {
                "storage_capacity_mwh": number("储能容量 MWh", "ops_", "storage_capacity_mwh",
                                               OPERATION_DEFAULTS, 0, 120, 5, "可储存电量的上限；0为零储能边界。"),
                "charge_limit_mw": number("充电功率 MW", "ops_", "charge_limit_mw",
                                          OPERATION_DEFAULTS, 0, 40, 1, "每小时最多输入的充电功率。"),
                "discharge_limit_mw": number("放电功率 MW", "ops_", "discharge_limit_mw",
                                             OPERATION_DEFAULTS, 0, 40, 1, "每小时最多输出的放电功率。"),
                "load_multiplier": number("负荷系数", "ops_", "load_multiplier", OPERATION_DEFAULTS, 0.5, 1.5, 0.1,
                                          "所选窗口各时段需求功率的倍数。"),
                "carbon_multiplier": number("碳价系数", "ops_", "carbon_multiplier", OPERATION_DEFAULTS, 0, 3, 0.1,
                                            "所选窗口合成碳价的倍数。"),
                "grid_capacity_multiplier": number("送出能力系数", "ops_", "grid_capacity_multiplier",
                                                   OPERATION_DEFAULTS, 0.1, 1.5, 0.1, "发电侧送出功率上限的倍数。"),
            }
            submitted = st.form_submit_button("运行储能对照", type="primary", icon=":material/play_arrow:",
                                             width="stretch")
        st.caption("发电侧储能 · 期初电量 0 MWh")
    if submitted or "operation_result" not in st.session_state:
        st.session_state["ops_saved_controls"] = {"window_name": window, **values}
        st.session_state.pop("operation_result", None)
        with st.spinner("计算连续SOC与有／无储能对照"):
            st.session_state["operation_result"] = run_operation_experiment(window, values)
    record = st.session_state["operation_result"]
    active_window = record["parameters"]["window_name"]
    synthetic_header("连续储能实验", f"{WINDOW_LABELS[active_window]} · 功率 MW / 能量 MWh · 独立连续窗口")
    p = record["parameters"]
    st.caption(f"结果所用参数：容量 {p['storage_capacity_mwh']:g} MWh · 充电 {p['charge_limit_mw']:g} MW"
               f" · 放电 {p['discharge_limit_mw']:g} MW · 负荷 {p['load_multiplier']:g}"
               f" · 碳价 {p['carbon_multiplier']:g} · 送出能力 {p['grid_capacity_multiplier']:g}")
    s = record["summaries"]["with_storage"]
    without = record["summaries"]["without_storage"]
    for col, label, value in zip(
        st.columns(4), ("有储能缺供 MWh", "无储能缺供 MWh", "窗口减少缺供 MWh", "期末库存 MWh"),
        (s["unserved_mwh"], without["unserved_mwh"], without["unserved_mwh"] - s["unserved_mwh"],
         s["closing_storage_mwh"]),
    ):
        col.metric(label, f"{value:,.3f}")
    st.caption(f"窗口 {s['window_hours']:.1f} h · 最大守恒残差 {s['max_abs_balance_residual_mwh']:.2e} MWh"
               f" · 运行 {record['run_id']}")
    paths, comparison, ledger, export = st.tabs(
        ["运行轨迹", "储能对照", "能量账本", "配置与导出"], key="operation_tabs")
    rows = record["cases"]["with_storage"]["rows"]
    with paths:
        generation = pd.DataFrame([{
            "时段": r["period"], **{TECHNOLOGY_LABELS[t]: r["generation_mwh"][t] for t in
                                   ("hydro", "nuclear", "wind", "solar", "coal", "gas")},
        } for r in rows])
        hours = 0.0
        soc_rows = [{"窗口经过时间 h": hours, "储能电量 MWh": 0.0}]
        for r in rows:
            hours += r["duration_hours"]
            soc_rows.append({"窗口经过时间 h": hours, "储能电量 MWh": r["storage"]["closing_energy_mwh"]})
        left, right = st.columns(2)
        with left:
            st.subheader("各时段发电量 · MWh")
            st.bar_chart(generation, x="时段", y=list(TECHNOLOGY_LABELS[t] for t in
                         ("hydro", "nuclear", "wind", "solar", "coal", "gas")),
                         color=TECHNOLOGY_COLORS, stack=True, height=260)
        with right:
            st.subheader("连续储能电量 · MWh")
            st.line_chart(pd.DataFrame(soc_rows), x="窗口经过时间 h", y="储能电量 MWh",
                          color=TEAL, height=260)
        st.subheader("窗口时序")
        st.dataframe(pd.DataFrame([{
            "时段": r["period"], "时长 h": r["duration_hours"], "终端需求 MWh": r["electricity_requested_mwh"],
            "已供 MWh": r["electricity_served_mwh"], "缺供 MWh": r["unserved_electricity_mwh"],
            "充电输入 MWh": r["storage"]["charge_input_mwh"], "放电输出 MWh": r["storage"]["discharge_output_mwh"],
            "期末SOC MWh": r["storage"]["closing_energy_mwh"],
        } for r in rows]), hide_index=True, width="stretch")
    with comparison:
        st.dataframe(pd.DataFrame([{
            "机制": OPERATION_LABELS[name], "缺供 MWh": item["unserved_mwh"],
            "受影响小时 h": item["shortage_hours"], "最大缺供 MW": item["max_shortage_mw"],
            "未用非燃烧电量 MWh": item["unused_noncombustion_mwh"],
            "运行变动成本 CU": item["resource_variable_cost_cu"], "碳支付 CU": item["carbon_payment_cu"],
            "合成燃烧排放": item["energy_related_synthetic_emissions"], "期末库存 MWh": item["closing_storage_mwh"],
        } for name, item in record["summaries"].items()]), hide_index=True, width="stretch")
        st.info("期末库存按实际留存；运行成本不含资本、固定成本及缺供损失。窗口结果不外推全年停电概率。",
                icon=":material/info:")
    with ledger:
        st.dataframe(pd.DataFrame([{
            "时段": r["period"], "发电 MWh": sum(r["generation_mwh"].values()),
            "SOC初 MWh": r["storage"]["opening_energy_mwh"], "已供 MWh": r["electricity_served_mwh"],
            "网损 MWh": r["grid_loss_mwh"],
            "充放损耗 MWh": r["storage"]["charge_loss_mwh"] + r["storage"]["discharge_loss_mwh"],
            "SOC末 MWh": r["storage"]["closing_energy_mwh"],
            "电力守恒残差 MWh": r["balance_residuals_mwh"]["electricity_with_storage"],
            "热电转换损失 MWh": r["thermal_conversion_loss_mwh"],
        } for r in rows]), hide_index=True, width="stretch")
        st.caption("电力发电＋SOC初＝已供＋网损＋充放损耗＋SOC末。热电转换损失在燃料接口另计。")
        with st.expander("逐时段原始日志"):
            st.json(rows)
    with export:
        download_record(record)


def data_view():
    st.title("官方数据与进度")
    st.caption("本次现场校验 · 官方观测、候选转录和合成实验分别保留")
    st.button("重新核对", icon=":material/refresh:", key="refresh_evidence")
    try:
        snapshot = workspace_snapshot()
    except (ValueError, KeyError, OSError, TypeError) as exc:
        st.error(f"工作区检查失败：{exc}")
        return
    report = snapshot["report"]
    formal = report["formal_input_check"]
    if formal["passed"]:
        st.success("已登记子集的证据结构与文件校验通过；准入仅限各自用途。", icon=":material/verified:")
    else:
        st.error("本次证据检查未通过，页面已撤销已核验标识。")
        for error in formal["errors"]:
            st.error(error)
    columns = st.columns(4)
    columns[0].metric("观测文件", str(len(snapshot["datasets"])))
    columns[1].metric("限定用途核验数值", str(snapshot["reviewed_measurements"]))
    columns[2].metric("已登记子集", str(len(formal["accepted_inputs"]) if formal["passed"] else 0))
    originals = report["workflow_check"]["original_inputs"]
    columns[3].metric("题给原件完整", f"{sum(i['unchanged'] for i in originals)} / {len(originals)}")
    st.caption(f"检查时间 {snapshot['checked_at']} · 数值单元可能跨文件重复，不等于独立样本数。")
    catalogue, details, progress = st.tabs(["观测目录", "来源与范围", "目标进度"], key="evidence_tabs")
    statuses = {"reviewed_scoped_subset": "限定用途已核验", "candidate_not_admitted": "候选待核验",
                "evidence_check_failed": "本次证据检查失败"}
    with catalogue:
        st.dataframe(pd.DataFrame([{
            "数据文件": Path(item["path"]).name,
            "年份": year_label(item["years"]),
            "数值单元": item["measurements"], "来源": "、".join(item["source_ids"]),
            "状态": statuses[item["admission"]],
        } for item in snapshot["datasets"]]), hide_index=True, width="stretch", height=500)
        st.caption("能源消费、宏观增速、装机三张十年表已转录齐全，尚待原表证据核验。"
                   "其余缺年、缺项和版本桥接分别处理。")
    with details:
        selected = st.selectbox("数据集", snapshot["datasets"],
                                format_func=lambda item: Path(item["path"]).name)
        st.caption("文件路径：" + selected["path"])
        st.write(f"**{statuses[selected['admission']]}**")
        st.write(selected["restriction"])
        dataset = read_observation(selected["path"])
        for sid in selected["source_ids"]:
            source = next((s for s in snapshot["sources"] if s["source_id"] == sid), None)
            if source:
                st.markdown(f"**{sid} · {source['publisher']}**")
                st.write(source["title"])
                st.link_button("官方来源 " + sid, source["url"], icon=":material/open_in_new:")
        if "rows" in dataset:
            table = pd.DataFrame(dataset["rows"], columns=dataset["columns"])
        else:
            table = pd.DataFrame(dataset.get("observations", []))
        st.dataframe(table, hide_index=True, width="stretch")
        with st.expander("口径、单位与证据"):
            st.json({"范围": dataset.get("scope"), "单位": dataset.get("units", dataset.get("unit")),
                     "说明": dataset.get("notes"), "文件校验值": selected["sha256"],
                     "证据文件": selected["evidence_files"]})
    with progress:
        labels = {"done": "已完成", "in_progress": "进行中", "pending": "待开展"}
        st.dataframe(pd.DataFrame([{
            "阶段": s["id"], "任务": s["title"], "状态": labels[s["status"]], "验收条件": s["acceptance"],
        } for s in report["stages"]]), hide_index=True, width="stretch")
        st.info("全国历史校准、基准及至少三种正式情景、论文和视频均待完成。"
                "运行界面与程序测试不代表科研验收。", icon=":material/assignment:")
        for error in report["workflow_check"]["errors"]:
            st.error(error)


with st.sidebar:
    st.caption("CSF 2026 · A题")
    st.markdown("### 多能源仿真实验台")
    workspace = st.radio("研究工作区", ["主体反馈实验", "连续储能实验", "官方数据与进度"], key="workspace")

try:
    if workspace == "主体反馈实验":
        agents_view()
    elif workspace == "连续储能实验":
        operations_view()
    else:
        data_view()
except (ValueError, KeyError, OSError, TypeError) as exc:
    st.error(f"本次运行未生成结果：{exc}")
