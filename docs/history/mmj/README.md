# A题研究工作区

更新日期：2026-10-17

研究主线：多主体决策下，能源转型的减排、供能安全与成本权衡，以及跨情景稳健政策组合。

## 执行入口与目标核对

当前总览见[任务进度与未解决事项](<../../14_goal_progress_review.md>)：逐项区分已实现、部分完成和未验收，并列出文档整理状态与后续顺序。

最新成果为[真实核电资产许可事件案例](<../../../outputs/asset_cases/index.md>)：将附件4的3条厂级记录对应到7台机组，接入8个官方许可事件，分开设计寿命、许可期限和实际退役。精确容量、商业投运与成本仍缺，不作全国容量或发电预测。128项标准库测试通过，详见[本轮审查](<../../../outputs/data_review/review_assets_20261017.md>)。

[真实总能源需求条件回算](<../../../outputs/calibration/index.md>)继续保留：两个最小历史子集共20值完成限定用途准入，实际输出2015—2021训练及2022—2024已接触留出结果。四种固定基线评估MAPE为0.2192%、1.8644%、3.6769%、5.2363%；给定已实现GDP，不是盲测或全国ABM校准。新增来源引起追溯版本更新，数值方案未变，旧结果保留。

历史原图在线核读，本地留存明确标注的人工文字摘录及同版方法说明；原图二进制和截图未取得，离线视觉复核能力受限。详见[本轮审查](<../../../outputs/data_review/review_demand_minimal_20261017.md>)。原80值整表仍为候选，不因子集准入自动批准。

[2024年度用电与可再生能源输入参考](<../../../outputs/current_assessment/electricity_inputs_2024_partial.md>)继续提供年度需求结构、抽蓄/生物质规模和发布版本比较；完整四维全国评价仍未完成。

[2024四维阶段评价](<../../../outputs/current_assessment/four_dimensions_2024_partial.md>)继续保留17项指标、进口金额结构、投资结构和天然气来源集中度保守界，列出模型接口及缺口。

[需求回算执行入口](<../../15_demand_hindcast_execution.md>)已接入两个最小子集，支持配置显式声明并完成审查的替代路径，按模块检查所需数据。来源记录改变仍拒算；无关模块失效不会阻止此模块。全部方法与逐年误差保留，不根据留出结果选择算法。

总体研究方向与题目一致，三问均未完整完成。四份附件已有890条标准记录，4个项目的既有部分字段核查保留，另将核电3条厂记录连接到真实机组许可案例。九个正式子集共112个数值限定准入，包括六个2024子集、两个历史需求子集及一个资产事件子集。日期与机组另计。尚未完成真实全国初始化、主体行为校准或远期预测。

- [文件导航](<FILES.md>)：原件、证据、候选、结果和临时文件的存放及使用规则。
- [观测数据目录](<../../../outputs/data_review/catalog.md>)：自动列出17个观测文件、准入状态、来源与用途限制。
- [历史数据缺口分类](<../../../outputs/data_review/history_readiness.md>)：三张十年表已有完整转录，主要待证据复核；其余缺年、字段和版本分别列清。
- [主体原型运行结果](<../../../outputs/prototype/report.md>)：完全合成的机制验证，附完整决策日志。
- [连续储能窗口结果](<../../../outputs/prototype/operations/report.md>)：六类电源、连续SOC及三种窗口下有/无储能对照，尚未与年度投资耦合。
- [真实历史接入契约](<../../11_calibration_input_contract.md>)：按模块列出字段、单位、准入和可识别性要求。
- [本地交互实验台](<../../12_workbench.md>)：主体调参、储能对照、决策日志和官方数据现场检查；运行run_workbench.ps1。
- [实验台操作手册](<../../13_workbench_user_manual.md>)：带截图的逐步操作、参数说明、默认结果及故障排查；[可编辑Word版](<../../../outputs/manuals/多能源仿真实验台操作手册.docx>)。
- [网站测试与修改记录](<../../../outputs/data_review/review_workbench_site_20261017.md>)：实际发现、修复、验证范围及后续建议。
- [WORKFLOW.md](<WORKFLOW.md>)：W0—W9任务、依赖、交付物和验收条件。
- [目标对齐审查](<../../06_alignment_review.md>)：现有进度、偏向及纠正措施。
- [总控提示词](<../../../prompts/00_master.md>)：与题目、附件和数据规则绑定的统一指令；prompts/内另有10份阶段提示词。
- [官方数据规则](<../../../workflow/official_data_policy.md>)：原文、脚注、统计口径、版本和证据留存要求。
- [需求矩阵](<../../../workflow/requirements.json>)：24项题目及用户要求的覆盖映射。

运行工作流状态检查并生成当前阶段的完整提示词：

```powershell
.\run_workflow.ps1
.\run_workflow.ps1 -Stage W1
.\run_workflow.ps1 -CheckFormalInputs
```

前两条生成outputs/workflow/status.md、status.json及next_prompt.md；指定阶段仅选择提示词，不执行研究任务或改变进度。第三条用于检查登记的正式观测输入证据：0表示结构检查通过，1表示工作流/文件错误，2表示正式输入尚未准入。目前九个正式子集通过检查，但全国模型的全部输入仍未齐备。检查不证明数据覆盖或模型科学有效性。run_analysis.ps1用于探索性计算，不替代此检查。

当前已核验成果：

- [附件标准化与用途报告](<../../../outputs/attachments/report.md>)：890条记录、9组同名项及官方字段修正。
- [附件字段字典](<../../07_attachment_data_dictionary.md>)：单位、日期、坐标和缺失处理边界。
- [2024电力初评](<../../../outputs/current_assessment/electricity_2024_partial.md>)：已核验发布版本的结构、网损、利用小时和投资，并列出四维评价缺口。
- [2024多能源初评](<../../../outputs/current_assessment/energy_2024_partial.md>)：生产、消费、发电结构、能源进口、碳交易及强度口径。
- [2024天然气初评](<../../../outputs/current_assessment/gas_2024_partial.md>)：用气结构、进口路线、来源集中性、表观消费差异与未闭合账本。
- [2024年度电力输入参考](<../../../outputs/current_assessment/electricity_inputs_2024_partial.md>)：需求分类和份额、抽蓄/生物质规模、利用率与多版本对照；[本轮审查](<../../../outputs/data_review/review_electricity_inputs_20261017.md>)。
- [统计口径与模型接口](<../../08_statistical_boundaries.md>)：将官方脚注转为需求、供给、转换和政府主体的数据约束。

运行附件处理：run_attachments.ps1。统一更新正式子集初评、数据目录和工作流状态：

```powershell
.\run_verified.ps1
```

该命令先检查证据，再生成三份独立初评、四维阶段评价、年度电力参考及真实需求基线回算，并刷新目录和历史状态；不运行全国预测，不批准候选数据。同一回算版本重复执行核对结果一致，不覆盖不同版本。

运行主体机制验证：

```powershell
.\run_prototype.ps1
```

读取examples/synthetic_agents.json及synthetic_operation_windows.json，分别生成outputs/prototype/的三组主体机制对照与operations/的六次连续窗口运行。所有参数是合成假设；主体步号不对应年份，运行窗口不代表真实小时观测。结果不能充当中国历史验证或全国正式情景。实现范围、参数字典和时序见docs/09_agent_prototype.md及10_operation_windows.md。

## 当前成果

本地交互界面入口：

```powershell
.\run_workbench.ps1
```

默认在http://127.0.0.1:8501运行。模型结果在浏览器会话内保存，可下载完整合成配置、结果和代码校验值；不覆盖正式观测或标准输出。依赖及另机安装说明见docs/12_workbench.md。全国历史校准和正式情景仍未完成。

| 材料 | 内容 | 状态 |
| --- | --- | --- |
| `docs/01_data_requirements.md` | 三问对应数据清单、优先级、字段与统计口径 | 首版完成 |
| `docs/02_model_design.md` | 模型边界、智能体行为、时序、核算与校准 | 设计草案 |
| `docs/03_experiment_design.md` | 四类情景、机制对照、优化与不确定性实验 | 设计草案 |
| `docs/04_attachment_audit.md` | 上一轮附件检查结果及待核查事项 | 初步审计 |
| `docs/05_foundation_status.md` | 数据处理、基线公式、核算实现及剩余任务 | 实现说明 |
| `data/sources.json` | 来源与版本登记 | 28项；官方网页/PDF页摘录各自保留范围和来源身份 |
| `data/observations/energy_consumption_2015_2024.json` | 官方十年能源消费总量与四类结构数据 | 已人工转录，需交叉复核 |
| `data/observations/power_capacity_2015_2024.json` | 十年年末装机 | 70个数值，同版年鉴 |
| `data/observations/macro_growth_2015_2024.json` | 十年实际GDP、能源和电力消费增速 | 30个数值，同版年鉴 |
| `data/observations/power_generation_2015_2024.json` | 十年发电量及技术分项 | 51个数值；旧年太阳能缺失，版本待衔接 |
| `data/observations/coal_balance_2015_2023.json` | 九年煤炭平衡 | 87个数值；存在统计口径变化，不用于连续校准 |
| `data/observations/petroleum_balance_selected_years.json` | 五年石油平衡 | 45个数值；缺年保留 |
| `data/observations/fuel_production_2023_2024.json` | 两年煤油气产量 | 6个数值；十年序列待补齐 |
| `data/observations/anchors_2025.json` | 2025年公报与统计局专题报告 | 20个候选数值；含摘要转录，需原文、脚注及版本衔接核验 |
| `data/observations/power_official_release_2024.json` | 2024电力装机、网损、利用小时及投资 | 10个已核验值，限定单独发布版本横截面用途 |
| `data/observations/energy_official_communique_2024.json` | 2024公报GDP、能源生产消费、发电、能源进口和碳交易 | 33个已核验值，限定独立公报横截面及口径分析 |
| `data/observations/gas_official_report_2024.json` | 官方发布报告的2024天然气用途、产量、进口及新增储气 | 20个已核验值；含报告采用的行业统计，限国内横截面 |
| `data/observations/gas_apparent_consumption_2024.json` | 发改委2024全年表观消费快报 | 2个已核验值；不与另一消费口径混算 |
| `data/observations/electricity_demand_official_2024.json` | 能源局2024用电总量、四类需求及同比等 | 11个已核验值；只作年度规模和结构参考 |
| `data/observations/renewable_operation_official_2024.json` | 能源局2024可再生技术容量、发电及利用率 | 15个已核验值；抽蓄能量和生物质排放未知，版本分列 |
| `data/observations/demand_energy_total_2015_2024.json` | 表9-2十年总能源消费最小子集 | 10值限定回算用途；原图在线核读、文字摘录留存 |
| `data/observations/demand_real_gdp_growth_2015_2024.json` | 表9-8十年实际GDP同比最小子集 | 10值限定近似链接指数与条件回算，不批准原宏观整表 |
| `src/energy_model/` | 核算、统计基线、缺失感知账本及合成主体反馈 | 煤油气/电力原型已运行，未完成全技术全国模型和校准 |
| `outputs/foundation/report.md` | 覆盖审计、历史指数与基线回算 | 可重复运行生成 |

当前17个观测文件共471个数值单元（不含年份、缺失、日期及派生指标）：旧候选359个保留，112个在明确范围内已核验。最小历史子集与候选列重复，数量不是独立样本数；资产案例另有7台机组和8个许可事件。总量/GDP可进行限定回算，结构、装机及其他历史范围仍待核验或桥接。尚未建立校准后的全国多智能体系统，未生成2030/2060预测。

统计局年鉴原图下载仍遇到连接/TLS错误。已通过直接打开官方页面，留存S17—S21的可见正文文本及S13所用段落、表行、脚注摘录（并非原始HTML）；S17覆盖完整表格，另4份能源局文件限定为项目字段证据。S04仍仅有检索摘要，全文与脚注待核对。

S22天然气报告原PDF下载也遇到TLS错误，采用官方PDF页面文本及截图视觉复核，明确未留存原二进制；S23为发改委官方网页正文。报告消费增速和快报表观消费增速分开，不用差额补库存，不把部门比例乘另一口径总量。

## 运行

在工作区执行：

```powershell
.\run_analysis.ps1
```

计算部分仅使用Python标准库，需要Python 3.10或以上。默认优先使用Codex捆绑Python；图表需要matplotlib，缺少时数值计算仍可运行并报告未生成图表。本机Python3.10具备matplotlib，可指定：

```powershell
.\run_analysis.ps1 -PythonPath 'C:\Users\44321\AppData\Local\Programs\Python\Python310\python.exe'
```

输出位于`outputs/foundation/`：数据审计、历史指数、单位统一的电力数据、需求基线和报告。图表为可选输出。输出文件包含原始输入SHA256，输入变化后应重新生成。

运行核算与数据处理测试：

```powershell
& 'C:\Users\44321\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -v
```

测试覆盖守恒、储能效率与边界、建设/退役时点、CCS只扣减一次、单位换算、缺失保留及留出数据不参与拟合，以及工作流依赖、原件哈希、官方域名伪装、证据缺失和输入篡改。它们不替代历史模型验证或独立来源校验。

## 阶段安排

1. 数据底座：补齐历史能源生产、分电源装机与发电、实际GDP、进出口与排放核算数据。
2. 全国基础模型：实现燃料供需、转换、容量存量、需求替代、主体投资与排放核算。
3. 历史验证：分开校准与验证年份，比较多个指标，确定可识别参数。
4. 情景与优化：先跑四类情景，再比较储能、互济、需求响应和碳价组合。
5. 区域与运行扩展：在数据允许时增加区域和连续极端事件窗口。
6. 提交准备：论文、三分钟视频、可运行程序、原始来源及数据处理说明。

正式基年候选为2025年。历史计划区间为2015—2025年；若核心分部门数据暂时仅到2024年，则以2024年统一校准，并把2025年作为补充检验或更新年。已有2022—2025基线结果曾被查看，不再称为未接触过的盲测。2026年月度数据不得直接当作全年历史值。

## 下一批具体工作

- 继续核查附件代表项目单位、年份、状态和期别；保留已完成的890条标准表及用途映射。
- 核对并归档现有核心数据的官方原文、脚注与版本，建立可使用的正式输入子集。
- 锁定煤炭统计修订的桥接，补齐天然气、终端部门需求及燃料热值和排放因子。
- 补齐旧年太阳能发电，完成跨年鉴发电版本衔接。
- 将“火电”拆分为煤、气、油、生物质等；缺分项时保留未分配项。
- 为各核心指标建立年份覆盖检查、来源版本检查和单位换算记录。
- 在合成需求与投资原型基础上接入真实数据；成本、寿命和工期无依据时在全国输入中保留缺失。
- 原型已实现基础反馈，后续增加多技术与储能、检查预期/预算机制，并按核验数据逐步校准；合成案例始终与全国输入分开。

赛题要求建议不少于十年数据、基准加至少三个对比情景、多智能体校准与验证、论文和视频等成果。详细依据为工作区原始赛题PDF。
