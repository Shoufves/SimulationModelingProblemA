# 文件导航与整理规则

更新：2026-10-17。

阅读顺序：README.md了解状态 → WORKFLOW.md确认验收任务 → outputs/data_review/catalog.md选择可用数据 → outputs/current_assessment/阅读当前已核验初评。原始题目始终优先。

|位置|放什么|使用边界|
|---|---|---|
|根目录PDF、附件1—4.xlsx|五份题给原件|不覆盖、不改名，哈希见workflow/provided_inputs.json|
|README.md、WORKFLOW.md、FILES.md|研究、执行、文件三个入口|保持最新，详细计算放下级目录|
|docs/|设计说明、附件字典、数据口径、操作源稿及目标进度|按编号递增；08口径、09主体、10连续运行、11历史接入、12实验台、13用户手册、14进度核对、15需求回算执行、16真实资产许可案例|
|docs/assets/workbench/|操作手册和网页验收截图|界面材料，不作为官方数据证据|
|prompts/|总控和W0—W9阶段提示词|不混入结果；生成的当前提示词在outputs/workflow/|
|workflow/|阶段状态、需求、正式输入清单与规则|只有实质验收后更新状态|
|data/observations/|结构化官方观测候选与已核验子集|以正式清单和数据目录判定准入，不凭文件名|
|data/raw/official/|官方证据留存|完整页与摘录在文件头明确；不能从派生报告反造证据|
|data/processed/|题给数据标准表|由处理脚本生成；原值和行号不丢失|
|data/sources.json及reviews文件|来源、观测审查、附件字段审查|来源改动可能使已审查哈希失效，必须实质复核|
|src/energy_model/|可复用模型/核算代码|包含合成主体原型，尚未实现校准的全国ABM|
|apps/、.streamlit/|本地Streamlit界面及样式/运行配置|界面调用模型；不把界面运行当历史校准|
|requirements-workbench.txt|界面直接依赖|模型标准库入口不依赖界面包；完整提交依赖锁定待W8|
|.venv-workbench/|本机界面运行环境|已忽略，不作为研究数据或提交材料|
|examples/|明确标注的合成参数配置|程序机制验证，不能当中国数据或正式情景|
|scripts/|生成、检查和下载程序|正式、探索用途在入口和说明中分别注明|
|tests/|有实际约束意义的测试|合成数据只在隔离测试中使用|
|tests/ui/|Streamlit交互测试|用专用环境单独运行，不影响标准库测试入口|
|outputs/attachments/|附件处理报告及诊断|由run_attachments.ps1重建|
|outputs/current_assessment/|正式子集支持的三份独立初评、四维阶段评价及年度电力输入参考|由run_verified.ps1重建；不是完整全国评价或预测|
|outputs/foundation/|候选历史的探索报告和基线|由run_analysis.ps1重建；尚未获正式准入|
|outputs/calibration/|已通过指定输入检查的真实条件回算，按版本分目录|当前仅总能源统计基线，不代表全国ABM校准；准备状态另放outputs/data_review/|
|outputs/asset_cases/|真实附件身份与官方资产事件案例，按版本分目录|当前为秦山7台机组许可状态；不当作实际运行容量或全国预测|
|outputs/prototype/|合成主体轨迹、决策和机制对照|由run_prototype.ps1重建；不作中国预测或历史验证|
|outputs/prototype/operations/|连续运行窗口的有/无储能对照|同一入口生成；小时单位独立于年度抽象步，无全年风险外推|
|outputs/manuals/|可编辑的用户操作手册|由docs/13源稿与截图生成；排版检查中间件只放tmp/|
|outputs/data_review/|数据目录、进度、日期化审查和下载日志|catalog/progress为当前入口；带日期文件为审计留档|
|outputs/workflow/|状态和下一阶段提示词|status为当前；validation.md为初次搭建历史记录|
|tmp/|PDF预览和隔离测试临时文件|非交付、非证据；本轮保留已有预览|
|各层__pycache__/|Python运行缓存|可重新生成，不参与研究或提交|

统一复现入口：

```powershell
.\run_verified.ps1        # 证据检查 + 初评/年度电力/真实需求回算/资产案例 + 目录/历史缺口/状态
.\run_prototype.ps1       # 合成主体机制对照 + 连续运行窗口，独立于官方观测输入
.\run_workbench.ps1       # 本地交互实验台；只读数据，实验在会话中计算与下载
.\run_attachments.ps1     # 题给附件标准表与异常诊断
.\run_analysis.ps1 -NoPlots  # 候选历史的探索性核算与基线
.\run_workflow.ps1 -Stage W4 # 仅生成主体模型阶段提示词，不执行模型
```

本轮采用目录索引和统一入口整理，保留原有文件路径，避免批量搬迁导致证据定位失效。以后新增数据文件以“主题_版本/年份”命名；下载失败记录用日期命名，不覆盖旧日志。可复算报告覆盖当前版本，实质审查记录按日期保留。

同日多轮审查增加主题，如review_gas_20261017.md，保留同日较早的review_20261017.md。天然气官方PDF未下载成功，本地只有S22_selected_capture.txt摘录，不存在可引用的本地原PDF；截图仅用于本轮视觉核对，未存为本地文件。对应失败及核对记录为capture_gas_20261017.json。

历史文件状态单独看outputs/data_review/history_readiness.md：区分已有十年转录待取证、跨版待桥接、实际缺年/字段。不要把examples/合成参数放入data/observations/或正式模型输入清单。新原型审查留存为review_agents_20261017.md。

连续运行扩展审查单独留存review_operations_20261017.md，不覆盖上一轮主体审查；正式校准字段和用途见docs/11_calibration_input_contract.md。outputs/calibration/现有真实总能源条件回算，全国ABM校准尚未完成。

网页操作验收单独留存review_workbench_site_20261017.md，不覆盖首次搭建审查review_workbench_20261017.md。手册截图存docs/assets/workbench/；浏览器下载样本存tmp/workbench-ui/，Word排版检查存tmp/workbench-manual-render/。

提交包尚未生成。最终打包只纳入确实使用的原件/证据、代码、说明、论文和视频，不纳入tmp、缓存及与结果无关的候选输出；W8需实际完成干净环境复现。

需求回算方案位于workflow/demand_hindcast.json，执行说明为docs/15_demand_hindcast_execution.md；早期准备审查review_demand_entry_20261017.md保留，首次真实运行审查为review_demand_minimal_20261017.md。两个10值最小历史子集已准入，原整表仍为候选。demand_readiness.json只表示输入准备状态，当前结果版本见outputs/calibration/index.md；新增来源使追溯版本变化，旧结果不覆盖。

实际输出的一致性核验单独保存在outputs/data_review/verification_demand_20261017.json，不放入官方证据目录。其129项算术/哈希断言与116项程序测试分开统计；均不替代官方原文、完整模型校准或界面验收。

资产案例说明为docs/16_asset_lifecycle_case.md，配置workflow/asset_case.json，数据qinshan_asset_permit_case.json，实际结果outputs/asset_cases/。本轮review_assets_20261017.md及verification_assets_20261017.json独立留存；S26—S28三份网页文字摘录放data/raw/official/，派生报告不能倒放为证据。前轮verification_demand_20261017.json记录来源追加前旧版本；本轮需求数值等同性另核。verification_assets_20261017_serialization_attempt.json是保留的首次检查方法不适用记录，最终结论看无attempt后缀的文件及审查说明。

问题一阶段汇总为outputs/current_assessment/four_dimensions_2024_partial.md及four_dimensions_2024.json，生成脚本为scripts/build_four_dimension_assessment.py。本轮审查和历史取证跟进分别为review_four_dimensions_20261017.md及capture_history_followup_20261017.json；不覆盖已有三份初评及各轮取证日志。

年度电力参考为outputs/current_assessment/electricity_inputs_2024_partial.md及electricity_inputs_2024.json，脚本scripts/build_electricity_inputs.py由run_verified.ps1调用。新增证据为data/raw/official/S24_page_capture.txt和S25_selected_capture.txt，观测按主题保存在data/observations/。审查留存review_electricity_inputs_20261017.md；不创建全国初始化或历史校准结果。

历史需求证据为data/raw/official/S01_demand_excerpt_20261017.txt和S06_gdp_excerpt_20261017.txt，明确属于人工核读文字摘录。原图二进制与截图没有本地文件，不把摘录或重画表格称为原件。结果入口为outputs/calibration/index.md；同一版本结果不可静默改写。
