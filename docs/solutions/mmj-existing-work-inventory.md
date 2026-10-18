# mmj：协作流程启用前的修改与具体问题对应

登记日期：2026-10-18。登记人：mmj。**本次交付是历史工作清点与问题归档，不是 P1/Q1 的完成方案。**

本分支 `docs/mmj-history-mapping` 按 mmj 本次明确指定，从 `7a65d068d19eea2f7dd8161a618a3ad8d66f98b8` 创建，作为本次历史清点的基线。此前开发目录仍停留在旧提交 `386436793e3d5afb0901dc66a0099f9bcec847b9`，其代码、结果和备份原位保留，没有整包搬进此分支。先前基于 `064b91d323f16ced13a98181eeb5f5a16609a978` 建立的本地文档分支保留，四份清点文件已备份后迁移到本分支，没有重置或覆盖原分支。

指定基线已经包含新版 `docs/17_git_collaboration.md`、`docs/rounds/P0_P1_Q1.md` 与 P0 基线证据，按这些共享文件核对本次范围。开工单保留编写时“准备中、正式 base 待锁定”的说明；用户已在本次会话明确指定上述分支起点，但本次未实时核对 Issue #1 的锁定状态，不代写三人批准记录，也不把本次历史清点算作 Q1 方案开发或验收。

以下 `MMJ-HIST-*` 是**本地历史问题登记号**，不是 GitHub Issue 编号，不是 P 轮次，也不表示三人已同意分工。yx、mmj、lb 后续仍按同一轮共同问题分别提交完整候选方案。

## 1. 先把已经动过的具体问题对应上

| 登记号 | 具体问题：原来缺什么、已经做了什么 | 对应文档要求 | 主要文件与历史证据 | 归档状态与后续位置 |
|---|---|---|---|---|
| MMJ-HIST-01 | 系统默认 Python 与项目依赖不匹配，入口可能调用错误解释器；建立项目环境、依赖入口与版本锁，新增 `run.cmd` 和数值能力检查，并修正 PowerShell 入口选择解释器 | F0 工程复现基础；协作 §0.2 环境检查、§4.3 完整交付、§9 复现门禁 | `requirements.txt`、`requirements-model.txt`、`requirements-lock.txt`、`run.cmd`、`scripts/check_environment.py`、`run_*.ps1`；历史 `docs/ENVIRONMENT_REPAIR_20261018.md`、`outputs/validation/environment_repair_summary.json` | 历史环境修复候选，单独准备 `fix/mmj-runtime` 类 PR。机器上的 `.venv` 不提交；版本锁的适用平台需明示 |
| MMJ-HIST-02 | LF/CRLF 转换破坏原件哈希核验；恢复有登记依据的原字节，增加恢复收据与换行保护；审计将 B/C 外部引用列为范围外，同时保留 A 题原件检查 | F0 原件保护；`AGENTS.md` 只读与用途契约；协作 §6.4 换行、§9 原件门禁 | `.gitattributes`、`scripts/repair_checkout_bytes.py`、`scripts/recover_original_downloads.py`、`tests/test_checkout_bytes.py`、`scripts/audit_workspace.py`；历史 `outputs/validation/*byte*`、`*recovery*`、`protected_session_check.json`、恢复备份 | 与模型方案分开评审。历史恢复数为210，不等于当前真实代码变更数。不得覆盖新主线已经修复或清理的文件，不得更改预期哈希来消除失败 |
| MMJ-HIST-03 | 界面测试把旧的数值单元数量写死，复现证据与实际准入子集不一致；按实际子集计算检查期望，补交互与浏览器验收 | F7 展示的工程准备；协作 §4.3 测试与证据随交付、§9 真实复跑 | `scripts/check_workbench_ui.cjs`、`tests/ui/test_workbench_app.py`；历史 `outputs/validation/ui_tests.json`、`workbench_20261018/browser-checks.json` 与截图 | 历史11项界面测试、9项浏览器检查通过。属于界面修复候选，不列入 P1/Q1 必需实现，不携带整包本机截图/配置作为代码改动 |
| MMJ-HIST-04 | 原规则原型没有共享燃料、连续库存/储能的优化运行，也没有年度发电投资与资金/工期队列闭环；新增分层服务 LP、Mesa 发电投资、完整未来资金承诺和配对/冻结诊断 | final D1—D3；F2 年度与运行闭环；F5/H02 的人工机制工具 | `src/energy_model/dispatch.py`、`annual.py`、`paired.py`、`scripts/run_coupled_model.py`、`examples/shared_fuel_lp.json`、`coupled_annual.json`、`workflow/coupled_requirements.json`；`tests/test_dispatch_lp.py`、`test_annual_coupling.py`、`test_paired_dispatch.py`；历史 `docs/17_coupled_engineering.md`、`outputs/validation/coupled_f2_acceptance.json` | F2 条件闭环候选；首轮新增32项、当时共166项测试。保留旧规则基线。不是全国初始化/校准，不是正式 H02 实测验证；与 Q1 分开 |
| MMJ-HIST-05 | 年度模型缺少用能主体和设备分代替换；新增同服务成本申请、旧设备预约、更新比例/完工约束、安装队列，以及发电与设备共享资金预算 | final D1/D2；yx §17.2/17.4/17.7；F2 设备与主体反馈 | `src/energy_model/devices.py`，及 `annual.py`、`dispatch.py` 的必要集成；`examples/coupled_devices.json`、`tests/test_device_replacement.py`；历史 `docs/18_device_replacement.md`、`outputs/validation/coupled_devices_acceptance.json` | 依赖 MMJ-HIST-04 的后续候选；新增21项、当时共187项。自然退出不能等新设备而延寿；改变自然寿命的反例不算同初态政策对照 |
| MMJ-HIST-06 | H01 需要分开 vE、vR、L，而原退出年只有硬寿命边界；新增合法政策退出队列、真实配套等待、三类退出规则、固定项目/自主投资分组、保留费和期末账面价值 | final E2；F5/H01；协作 §4.3 完整配置/测试/证据与同输入比较 | `src/energy_model/transition.py`、`h01.py`，及 `annual.py` 集成；`scripts/run_h01_experiment.py`、`examples/h01_experiment.json`、`tests/test_h01_transition.py`；历史 `docs/19_h01_conditional.md`、`outputs/validation/h01_conditional_acceptance.json` | 依赖 MMJ-HIST-04/05 的人工条件实验候选；新增21项、共208项。45组中26组满足共同边界、19组电力缺供。正式 H/ε、全国 H01、前瞻候选规则均未完成 |
| MMJ-HIST-07 | 上述修复/实现改变运行入口、阶段说明及测试/复现结果；需要让导航、状态和产物指向实际版本 | 协作 §4.2 单一提交目的、§4.3 共享入口最小改动；F0—F7 状态如实记录 | `README.md`、`WORKFLOW.md`、`docs/RUNNING.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`run.py`、`workflow/final_route.json`、`outputs/workflow/`、`outputs/data_review/` 与验证记录 | 属于多项问题的集成修改，不能整个文件归给某一问题。后续每个候选只提取自身必要改动；不得以刷新结果数量充当新研究成果 |
| MMJ-HIST-08 | 协作流程刚引入，旧成果没有共同轮次、base、个人方案与独立评审记录；本次补做逐项映射、文件指纹和移交范围 | 协作 §0/§0.2/§5.0/§12.5；P0 准备工作 | 本文、`outputs/validation/mmj_historical_change_inventory_20261018.json`、`mmj_historical_mapping_evidence_20261018.json` | 本次文档准备分支的唯一目的。不是新增科学方案，不创建 `p0/mmj`，不提前创建或占用 `p1/mmj` |

历史证据路径是**此前开发目录中的仓库相对路径**，没有被当作新主线中已存在的文件。对应文件指纹和摘录已登记于本分支的两份 JSON；实现和大批实验产物仍等待各自候选 PR。

## 2. 现场修改不等于478项功能修改

对旧开发目录 `git status --porcelain -z --untracked-files=all` 的快照逐个与其旧 HEAD 原字节比较：

| 分类 | 路径数 | 解释及处理 |
|---|---:|---|
| 实际字节与旧 HEAD 完全相同 | 213 | Git 状态/换行处理造成的表面修改，不算新增功能，不为“清干净”批量覆盖 |
| 仅 LF/CRLF 布局不同 | 22 | 归入原件/换行核对，须按证据契约判断；不作为功能实现提交 |
| 有实质内容差异的已跟踪文件 | 31 | 主要是共享入口、说明、审计修复、界面测试与运行产物，逐项归档 |
| 未跟踪文件 | 212 | 包含新增源码/测试/配置，也包含备份、截图、多次实验结果与用户提供的协作文件；不等于212个代码文件 |
| 合计 | 478 | 每条路径的类型、体积、SHA256、历史问题映射见逐文件清单 |

未跟踪文件中未发现单个≥50 MiB文件；这不代替后续暂存清单的体积/内容检查。清单不读取 `data/restricted/`，不包含本机绝对路径、认证信息或虚拟环境。

历史修复使许多文件恢复到旧 HEAD 原字节，因此“曾修复210个文件”与“现在只有22个仅换行差异”并不冲突。也不能把已有原始观测、原模块或其他人的资料归为 mmj 新编写的内容。

## 3. 与当前 P1/Q1 具体要求的对应

远端准备开工单把 P1 定为 Q1“当前各种能源发展现状评估”，不是 F2 或 H01 开发轮次。对应关系如下：

| Q1验收 | 可参考的旧工作 | 仍缺的本轮交付 |
|---|---|---|
| A1 题面覆盖 | 既有统计/附件/17项局部指标及原有资料目录；环境修复只提高可复现性 | P1完整历史规模/结构/区域/进出口/价格与九类能源角色交付，不能以设备模型代替 |
| A2 四维定量 | 既有局部四维结果，未由本次清点扩展准入 | 有来源、同服务、同价格年的经济性比较及协调分析；本轮指标与缺口说明 |
| A3 来源与同源去重 | MMJ-HIST-02 的原字节保护和原九子集用途约束 | `workflow/q1_inputs.json`、实际采用数据与逐项来源，新增用途实质审查 |
| A4 静态核对/Q2交接 | 原账本边界、MMJ-HIST-04/05可提示后续模型需要哪些字段 | Q1的 `static_balance.json`、`model_handoff.csv`；不能直接宣称全国初态齐备 |
| A5 独立复现 | MMJ-HIST-01 的环境入口经验 | `run.py q1 --output-dir outputs/q1/p1_mmj` 及本轮独立复现；旧人工实验入口不能替代 |
| A6 工程门禁 | 历史208项测试、九子集准入与人工运行记录，仅对旧工作树有效 | 在正式共同 base 和最终待评审提交上复跑测试、审计、密钥扫描及Q1入口 |
| A7 两人批准 | 本次之前没有相应PR与同SHA评审记录 | yx、lb分别对最终同一提交评审；至少一人复跑基础检查和Q1入口 |

`docs/solutions/p1-mmj.md` 与 `outputs/q1/p1_mmj/` 尚不是此前实现的成果，不以空文件或改名旧报告补齐。本次也不把F2/H01成果登记为Q1已验收。

## 4. 历史验收与当前门禁必须分开

历史记录可复核的递进为：环境阶段134项核心及工程测试；条件运行/年度发电阶段166项；设备阶段187项；H01阶段208项。H01有45组年度模拟、366次运行模型调用（含51次当前条件重放）、1464次底层LP调用。

**这些是旧开发目录的真实自测记录，未在本分支重新运行，也不是当前主线的测试数量。** 清点文档只摘录记录与文件哈希。未把本地环境、未发布代码或未发布输入算作其他两人已经能复现的共享成果。

旧开发目录严格审计为12/13：唯一失败为只读 Gemini 文件的历史LF/CRLF差异。三份只读文件与该轮开始时一致、历史原字节已另存，并不能把严格审计写成通过。按协作 §9，该状态仍阻止相应历史实现候选合并；本次不修改只读原件、不更新期望哈希、不放宽门禁。新主线的审计状态须另行核对，不能拿旧结果覆盖它。

当前主线相较旧 HEAD 还包含目录/原件清理、协作规程、扫描器及相应审计改动。后续迁移先比较这些增量，不以整份旧文件覆盖新主线，尤其不能把已清理的原始内容重新带入仓库。

## 5. 后续提交边界

1. 本次仅清点文档、逐文件归属/指纹及历史证据摘要；不暂存旧工作树的模型、数据、备份或实验全集。
2. 环境修复、原字节/换行保护、界面修复分别形成有限目的的准备或修复候选；已有主线修复先去重，需两人认可后再合并。
3. F2→设备更新→H01存在依赖，保留为后续问题候选。在三人约定相应任务时，使用当轮正式共同 base，补齐各自必要入口、源码、配置、测试和实际产物后再提PR。
4. 共享入口按问题提取必要改动；`outputs/`逐个选择。历史备份与本机路径不整包提交，不用`git add -A`或强推搬运工作区。
5. P1/Q1按共享开工单与 Issue 的范围推进；用户已指定本次分支起点为`7a65d068d19eea2f7dd8161a618a3ad8d66f98b8`，本次仅创建历史清点文档分支。正式 Q1 开发时仍核对 Issue 的锁定状态、三人共同输入和验收，不把历史 F2/H01 工作整包当作`p1/mmj`方案。`【具体问题】`应填写那一轮的共同问题和验收。
6. mmj已授权本任务commit、普通push和创建PR；不授权直接推main、替两人批准或自行合并。PR须如实区分“清点已完成”与“实现候选待复验”。

本次分支起点已按用户指定落实；尚无两位评审人针对本次最终提交的同SHA批准，不据此登记任何历史问题已合并或 Q1 已完成。

本次文档核对已验证478条路径全部有映射、分类合计一致、源文件/历史验收收据哈希一致、参考主线与分支正确、README入口可解析，且本次四个文件没有本机绝对路径或≥50 MiB文件。使用主线扫描器的`scan_bytes`对这四个拟提交文件检查，无Google密钥格式命中；未执行会遍历整个目录的默认扫描，也未读取受限数据或虚拟环境。实际核对结果见证据摘要的`inventory_validation`；未复跑历史模型或冒称全仓库门禁通过。
