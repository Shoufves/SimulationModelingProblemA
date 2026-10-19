# 运行与复现

当前 Q2 入口见 [v13 运行与失败记录](solutions/p2-iteration-v13.md)。复跑使用新目录：

```powershell
python -B -X utf8 scripts/run_q2_allocation_candidate.py --config workflow/q2_candidates/v13_allocation.json --output-dir outputs/q2/v13_reproduce
```

以下旧轮次命令保留用于复现历史结果。

2026-10-19 后续：[终端服务与设备替代映射](solutions/p2-device-service-mapping.md)已完成 16 条条件路径、165 个服务年度核对及两环境复现；新增按旧设备实际利用率估值的可选规则。405 项测试通过，v12 原结果不变，全国缺口仍保留。

2026-10-19 较早轮次检查见 [v12 联合校准与缺口说明](solutions/p2-iteration-v12.md)：250 次新增训练，累计 5995 次；油占比误差下降，但油、气、风、光仍未通过，六组全国输入及 S0/全国灵敏度仍未完成。以下较早轮次记录保留其原状态。

较早的 Q2 v6 诊断；来源、光伏年份/上限消融、失败证据及复现见 [v6 迭代说明](solutions/p2-iteration-v6.md)。快速重跑（输出目录必须尚不存在）：

```powershell
python -B -X utf8 scripts/build_q2_solar_candidate.py
python -B -X utf8 scripts/run_q2_historical_candidate.py --manifest workflow/q2_candidates/v6/manifest.json --output-dir outputs/q2/historical_candidate_v6_reproduce
python -B -X utf8 scripts/run_q2_candidate_sensitivity.py --config workflow/q2_candidates/v6_sensitivity.json --output-dir outputs/q2/v6_response_reproduce
python -B -X utf8 scripts/run_q2_solar_ablation.py --output-dir outputs/q2/v6_ablation_reproduce
```

这是含真实原件和明确假设的历史诊断，五项质量门槛仍失败；不替代正式全国准入、S0 或外部评审。下文 v1 复现命令继续用于原始候选回归。

当前 Q1 已通过整合 PR #6 合入 main，详见[轮次日志](ROUND_LOG.md)及[整合说明](solutions/p1-yx-integration.md)。`python -B -X utf8 run.py q1` 默认写入 `outputs/q1/p1_yx/`，保留 lb 原候选产物。完整交付核验仍运行 `python -B -X utf8 scripts/review_q1_delivery.py`，本次证据写入 `outputs/q1_review/lb_mmj_integration/`；其中两次 Q1 分别写入 `p1_yx`、`yx_reproduction`。显式重建 `scripts/prepare_q1_review.py` 会重新核对 mmj 已用 IRENA 原文再重建六条成本参数，并拒绝未经重新审查的 lb 原输入变化。

在A题目录执行。Python 3.11及以上；本轮使用本机捆绑Python 3.12.14。核心模型和测试主要使用标准库；附件需要openpyxl，yx/lb离线提取需要pandas/numpy/lxml/pypdf/pdfplumber。

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-data.txt
.\.venv\Scripts\python -B -X utf8 run.py audit
.\.venv\Scripts\python -B -X utf8 run.py test
```

新环境安装命令供迁移到其他机器时使用。早期整理环境见 `outputs/validation/environment.json`；Q2 已另建干净环境安装 Mesa/SciPy，精确版本与检查见 `requirements-q2-lock.txt`、`outputs/q2/development_checks.json`。旧 `.venv-workbench` 不作为数据或提交材料。Q2 工程闭环已实现，全国数据校准与预测仍未验收。

| 命令 | 做什么 | 输出/边界 |
|---|---|---|
| `python -B -X utf8 run.py audit` | 检查原件、保留记录、原文备份、final引用、语法、唯一键及隔离 | outputs/validation/workspace_audit.json |
| `python -B -X utf8 run.py test` | 原测试和本轮新增边界测试 | outputs/validation/tests.json；不替代科学验证 |
| `python -B -X utf8 run.py q1 --output-dir outputs/q1/p1_yx` | Q1历史、四维、区域、可比成本、静态账及后续接口 | 本分支候选；离线核查workflow/q1_inputs.json；缺项显式保留 |
| `python -B -X utf8 run.py attachments` | 重建附件标准表及用途报告 | data/processed/attachment_assets.json、outputs/attachments |
| `python -B -X utf8 run.py verify` | 检查原九子集，再重算初评/真实需求条件回算/许可案例 | outputs/current_assessment、calibration、asset_cases |
| `python -B -X utf8 run.py prototype` | 合成主体机制与六次连续窗口对照 | outputs/prototype；非全国实测或预测 |
| `python -B -X utf8 run.py baseline` | 原候选历史探索性基线 | outputs/foundation；不扩大正式准入 |
| `python -B -X utf8 run.py catalog` | 重建统一目录和统计局去重视图 | data/catalog、data/processed/unified |
| `python -B -X utf8 run.py status` | 原W0—W9及子集准入状态 | outputs/workflow；完整研究状态看WORKFLOW.md |
| `python -B -X utf8 scripts/prepare_external_data.py` | yx离线重建27张表 | 保留旧统计候选窗口说明；正式窗口仍以final为准 |
| `python -B -X utf8 scripts/audit_data_package.py` | yx原文件/表格质量检查 | data/catalog/package_audit.json |
| `python -B -X utf8 run.py reproduce-lb --recipe trade` | EI煤/管道气/LNG、CCTD来源表 | outputs/validation/lb_reproduce_trade.json |
| `python -B -X utf8 run.py reproduce-lb --recipe international` | EIA通道/外部季度等表 | 同名validation记录 |
| `python -B -X utf8 run.py reproduce-lb --recipe ai_trade` | 原油/LNG/算力锚点转录 | 同名validation记录 |
| `python -B -X utf8 run.py reproduce-lb --recipe national` | lb全国统计/OWID/价格/排放等提取 | 同名validation记录；保留价格隔离 |

所有命令失败时返回非零。缺输入、证据变更和数值失败不得写成成功。lb重建在 `tmp/reproduce_lb/` 使用普通副本，完成后清理；不会以可写硬链接改变原件。个别脚本包含人工转录常量，重建一致只证明程序再现，不能替代原图核对。

Windows受限沙箱可能禁止Python临时目录的ACL操作，原有测试会报WinError 5。这属于执行环境问题；在允许创建和清理临时夹具的本地终端运行同一命令，不应删除准入检查来使测试通过。

## 问题一运行环境

Python3.11及以上；初次安装`python -m pip install -r requirements-q1.txt`。数值处理只用标准库，ReportLab生成四张SVG。运行`q1`时不联网，不自动重新生成输入指纹或改变原准入契约。结果目录必须位于`outputs/q1`内，非本实现拥有的非空目录拒绝覆盖；独立复现可改为`outputs/q1/yx_reproduction`。失败返回非零，失败尝试记录不冒充旧成功结果。

本工程按原字节检查输入与代码，克隆时使用`git clone --config core.autocrlf=false <仓库地址>`，已有目录按协作规程§6.4关闭本地自动换行转换。遇到指纹不符时检查签出与文件变动，不重新生成指纹来绕过。`scripts/review_q1_delivery.py`允许共同base之后的提交及独立评审的detached HEAD，不要求当前HEAD仍等于起跑线。

`docs/solutions/p1-yx-integration.md`记录两份候选采用关系与提交前历史；当前合并状态和评审授权见`docs/ROUND_LOG.md`。原lb报告与产物作为历史交付保留。P2任务见`docs/rounds/P2_Q2.md`，当前本地实现进展及完整限制见[问题二实现记录](solutions/p2-yx.md)。

## 问题二开发入口（尚未全国验收）

安装 `python -m pip install -r requirements-q2.txt` 后可运行 Mesa/SciPy 工程闭环。新增测试也需要该依赖；不能仅按早期“核心测试主要标准库”的环境执行当前全部测试。

```powershell
python -B -X utf8 scripts/prepare_q2_history.py
python -B -X utf8 scripts/prepare_q2_technology.py
python -B -X utf8 run.py q2 --config workflow/q2_inputs.json --output-dir outputs/q2/p2_yx
python -B -X utf8 run.py q2 --config examples/q2_engineering.json --output-dir outputs/q2/engineering_yx
```

前两条离线核验并重建已审历史候选与技术参照；全国入口目前因输入未齐返回非零，具体缺口见 `workflow/q2_inputs.json`；工程入口为合成复现，成功不代表全国历史校准或 2030/2060 预测。新运行不会隐式联网、改写审查哈希或把旧成功目录冒充本次成功。

`python -B -X utf8 scripts/build_q2_engineering_fixture.py` 可重建纯合成夹具及其指纹，仅用于工程测试，不读写全国数据审查。版本 2 修正服务能力替换比例；新版质量门槛和生命周期队列有独立输出。科学计算后失败的诊断保存在 `outputs/q2/failed/<运行目录>/<run_id>/`，不作为成功产物。

复算 2014 年 CEADs 部门初态候选时，另安装 `python -m pip install -r requirements-q2-data.txt`，再执行 `python -B -X utf8 scripts/prepare_q2_sector_state.py`。原始 XLS 保持不变，输出仅覆盖原有 30 省，不自动准入全国模型。

## 可选界面

```powershell
.\.venv\Scripts\python -m pip install -r requirements-workbench.txt
.\run_workbench.ps1 -PythonPath .\.venv\Scripts\python.exe
```

界面依赖清单沿用原mmj版本。操作手册与截图保留；本次整理以命令行数据/模块复现为验收，未宣称重新完成浏览器交互验收。界面仍显示合成实验和局部证据，不能当全国预测演示。

## 版本与恢复

`archive/organization_20261017/file_disposition.csv` 逐文件记录旧路径→新位置或删除理由。修改过的文档/脚本原字节保存在 `edited_originals.zip`；复算前的结果与目录在 `prior_results.zip`。恢复时按该映射提取单个文件，不把全部旧目录覆盖回当前工程。

### Q2 全国 2014 核算原件转录

```powershell
python -B -X utf8 scripts/prepare_q2_nbs2014.py
```

校验六张 NBS 2016 原图和用途审查的固定指纹，重建 169 个 2014 年账户单元格、23 项算术核对和 4 类边界差异。只依赖标准库；输出位于 `data/processed/q2/nbs2014_*`。该步骤不调整原表、不刷新审查、不把留白填零，也不自动批准全国主体初态。

Q2 工程夹具 v3 使用显式建设付款比例、净现值和预期残值。完整可复建入口为 `python -B -X utf8 scripts/build_q2_engineering_fixture.py`，仅更新合成示例及其合成目标；正式全国输入不得用该脚本生成。全国运行还需要被固定指纹的 `national_reporting` 输入：能量与 CO₂ 映射、同口径历史锚点、GDP 可比价基数、非能源/净移除假设和逐项政策原文定位。缺这些资料时正式入口仍返回非零。

### Q2 初态参照与历史技术资料

```powershell
python -B -X utf8 scripts/prepare_q2_nbs2014.py
python -B -X utf8 scripts/prepare_q2_initialization_references.py
python -B -X utf8 scripts/prepare_q2_technology_2010.py
python -B -X utf8 run.py catalog
```

初态参照脚本依赖上一条产生的全国账户，离线重建 22 项燃料默认值、42 条电力参照、9 组互不重叠装机和 56 条具名燃料热量归一记录。6 个用量缺失保持缺失；NEA 发电合计与分项相差 11 亿 kWh，保留为未分配差，不命名为技术或舍入误差。

2010 技术脚本分别输出 19 个正文净容量样本、20 个附录项目样本、24 项方法参数和 8 条一致性诊断。正文煤炭热价与附录吨价/热值、正文气价与上海报价、玉门风电成本的 3 类差异未自动消除。金额为 2008 美元或按原汇率换算的 2008 人民币，不与 2014 名义建设支出直接相加。上述两个脚本均只依赖标准库，不联网或自动扩大准入；真实来源已进入统一目录，复跑校验固定原件与已审来源记录。

### Q2 历史政策与真实候选诊断

```powershell
python -B -X utf8 scripts/prepare_q2_policy.py
python -B -X utf8 scripts/build_q2_historical_candidate.py
python -B -X utf8 scripts/run_q2_historical_candidate.py --output-dir outputs/q2/historical_candidate_v1_reproduce
```

政策脚本离线核验2009风电和2013光伏原件，重建8条限定用途记录，不生成已批准的全国合同。构建器复核已冻结v1输入的一致性；若同版本内容变化，明确失败，不覆盖已经看过留出的模型配置。

诊断入口实际运行81个2015—2021训练组合，按训练损失同时选择行为规则和参数，再运行2022—2024已接触留出。输出目录必须是尚未使用的新目录；再次执行时换一个目录名，避免覆盖历史证据。运行成功表示实验已执行，`historical_quality.json`中的六项失败和`national_acceptance: false`仍有效。这一入口不能代替正式`run.py q2`准入，也不输出全国2030/2060结论。

固定环境依赖见`requirements-q2-lock.txt`，具体Python、库、FreeType和代码指纹见运行清单。同一锁定环境独立目录的17个产物逐字节相同；已测试的另一构建环境全部数值账本和规范SVG相同，但Pillow/FreeType版本不同使PNG像素不同。复核科学图以SVG为规范版本，不承诺不同字体栅格器的PNG字节一致。完整证据在`outputs/q2/candidate_v1_reproduction.json`。

### Q2 v5 全国能源表与配对响应

```powershell
python -m pip install -r requirements-q2-data.txt
python -B -X utf8 scripts/prepare_q2_national_balance.py
python -B -X utf8 scripts/build_q2_fuel_candidate.py
python -B -X utf8 scripts/run_q2_historical_candidate.py --manifest workflow/q2_candidates/v5/manifest.json --output-dir outputs/q2/v5_reproduce
python -B -X utf8 scripts/run_q2_candidate_sensitivity.py --output-dir outputs/q2/v5_response_reproduce
```

能源表提取使用openpyxl3.1.5读取未修改XLSX的2014工作表，1260个数据单元和60项算术核对；旧文件保留当时三项差额，后续煤炭类别桥接见下节，天然气差额仍未解释。v5执行750组训练，保留原阈值和已接触留出，五项门槛失败。响应入口固定v5训练选择，实际运行GDP增速、技术降本和碳费的27组历史条件路径；不属于全国2025—2060灵敏度验收。输出须使用新目录。参见[v5完整说明](solutions/p2-iteration-v5.md)。

### Q2 煤炭桥接与 APEC 部门能源账

```powershell
python -B -X utf8 scripts/prepare_q2_coal_bridge.py --output-dir tmp/q2/coal_bridge_reproduce
python -B -X utf8 scripts/prepare_q2_apec_balance.py --output-dir tmp/q2/apec_balance_reproduce
python -B -X utf8 -m unittest discover -s tests -p test_q2_balance_bridge.py
```

两个入口只读核对原件、源记录和审查指纹，分别输出15项煤炭聚合桥接、6840格APEC原表及54项部门/产品条件区间。APEC破折号保留缺项，产出附列单位独立处理；区间不是设备/有效服务。独立副本在两种环境均复现7个文件，完整回归304项通过。见[边界与推导](solutions/p2-balance-bridge.md)，不构成全国初态或预测验收。

### Q2 v7 共用建设/接入瓶颈对照

2015年核电补充原件与逐机组容量/开工状态另见[核电参照核验](solutions/p2-nuclear-reference.md)。离线入口为`python -B -X utf8 scripts/prepare_q2_nuclear_capacity.py --output-dir tmp/q2/nuclear_capacity_reproduce`，不修改v7候选。

```powershell
python -B -X utf8 scripts/build_q2_deployment_candidate.py
python -B -X utf8 scripts/run_q2_historical_candidate.py --manifest workflow/q2_candidates/v7/manifest.json --output-dir outputs/q2/v7_reproduce
python -B -X utf8 scripts/run_q2_deployment_ablation.py --output-dir outputs/q2/v7_ablation_reproduce
```

四种结构×三种原行为规则共12组训练，零新增数值参数；选中原结构，五项历史门槛仍失败。四条配对路径记录年额度、技术活动/利用率及审批/队列；技术额度是显式研究假设，不是观测电网能力。313项完整测试通过，候选与消融的全部数值产物在两个环境一致，v6完整控制账不变。详见[v7解释与复现](solutions/p2-iteration-v7.md)。

### Q2 v8 核电实际审批结果回放

```powershell
python -B -X utf8 scripts/build_q2_permit_candidate.py
python -B -X utf8 scripts/run_q2_historical_candidate.py --manifest workflow/q2_candidates/v8/manifest.json --output-dir outputs/q2/v8_reproduce
python -B -X utf8 scripts/run_q2_permit_ablation.py --output-dir outputs/q2/v8_ablation_reproduce
python -B -X utf8 scripts/run_q2_candidate_sensitivity.py --config workflow/q2_candidates/v8_sensitivity.json --output-dir outputs/q2/v8_response_reproduce
```

CNS8原文明示2016—2018零建造许可颁发；逐年阻断新审批，保留既有队列。3组训练和27组响应成功，核电项通过原门槛，尚有4项失败；326项测试通过。两个环境独立复现全部数值产物，PNG差异限制不变。见[v8证据及边界](solutions/p2-iteration-v8.md)，不构成全国预测验收。

### Q2 v9 联合风光扩张率及建设结构比较

```powershell
python -B -X utf8 scripts/build_q2_joint_deployment_candidate.py
python -B -X utf8 scripts/run_q2_historical_candidate.py --manifest workflow/q2_candidates/v9/manifest.json --output-dir outputs/q2/v9_reproduce
python -B -X utf8 scripts/run_q2_joint_deployment_comparison.py --output-dir outputs/q2/v9_comparison_reproduce
python -B -X utf8 scripts/run_q2_candidate_sensitivity.py --config workflow/q2_candidates/v9_sensitivity.json --output-dir outputs/q2/v9_response_reproduce
python -B -X utf8 scripts/prepare_q2_policy_timeline.py --output-dir tmp/q2/policy_timeline_reproduce
```

输出使用新目录。486组训练、三条各自训练选参的路径和27组响应已执行；99文件独立快照在两环境复现所有数值与SVG。训练损失降低但风电留出误差升至42.61%，仍有四项失败，详见[v9报告](solutions/p2-iteration-v9.md)。[历史电价核验](solutions/p2-policy-timeline.md)另有12文件、两环境3项产物复现；未改变上述冻结模型。当前337项测试通过，全国S0尚未验收。

### Q2 历史货币口径参照

```powershell
python -B -X utf8 scripts/prepare_q2_currency_bridge.py --output-dir tmp/q2/currency_bridge_reproduce
```

17年逐年因子与5条用途绑定见[货币桥接](solutions/p2-currency-bridge.md)。两环境2项产物一致；当前337项完整测试通过。只作事后单位核对，不把未来实际汇率或平减输入历史投资预期，未改变v9模型。

### Q2 名义电价合同与有限批次机制对照

```powershell
python -B -X utf8 scripts/build_q2_nominal_policy_episode.py
python -B -X utf8 scripts/run_q2_nominal_policy_episode.py --output-dir outputs/q2/nominal_policy_episode_reproduce
```

使用新输出目录；每次执行全部七条路径并逐批次核对发电量、电价差及现金。见[实现与边界](solutions/p2-nominal-contracts.md)。两个环境各15项产物一致，当前344项测试通过；研究条件仅覆盖假定合格的2015申请批次，不能替代完整政策日历或全国预测。

### Q2 v10 初始光伏队列与风光建设速度

```powershell
python -B -X utf8 scripts/build_q2_pv_queue_candidate.py
python -B -X utf8 scripts/run_q2_historical_candidate.py --manifest workflow/q2_candidates/v10/manifest.json --output-dir outputs/q2/v10_reproduce
python -B -X utf8 scripts/run_q2_joint_deployment_comparison.py --config workflow/q2_candidates/v10_comparison.json --output-dir outputs/q2/v10_comparison_reproduce
python -B -X utf8 scripts/run_q2_candidate_sensitivity.py --config workflow/q2_candidates/v10_sensitivity.json --output-dir outputs/q2/v10_response_reproduce
```

新目录要求与旧版本相同。1458组训练、七条完整比较、27组响应均执行；原v9的486组控制逐项相同。新增队列是显式待校准初态，不是实测项目清单。349项完整测试通过，四项历史门槛仍失败；见[v10结果与复现](solutions/p2-iteration-v10.md)，不能将其作为全国S0。

### Q2 2024年底核电设备及队列参照

```powershell
python -B -X utf8 scripts/prepare_q2_nuclear_state_2024.py --output-dir tmp/q2/nuclear_state_2024_reproduce
```

85条原表记录、身份与时点冲突及NBS差异见[专用说明](solutions/p2-nuclear-state-2024.md)。11文件独立副本在两环境重建3项产物一致；当前354项回归通过。该参照不自动生成许可、退役、资金或未来投运路径。

### Q2 活动量与交通参照

```powershell
python -B -X utf8 scripts/prepare_q2_transport_activity.py --output-dir tmp/q2/transport_activity_reproduce
python -B -X utf8 -m unittest discover -s tests -p test_q2_activity.py -v
python -B -X utf8 -m unittest discover -s tests -p test_q2_transport_activity.py -v
```

详见[计算及口径](solutions/p2-activity-drivers.md)。132个单元格、22项加总和6条参照可离线重建；13文件副本在两个环境各4项产物逐字节一致。算术错误或原件篡改会阻断导出。活动量不是燃料强度，营业性交通不是全部交通；全国模型准入状态不变。

### Q2 非能源原料分账试验

```powershell
python -B -X utf8 scripts/build_q2_nonenergy_episode.py
python -B -X utf8 scripts/run_q2_nonenergy_episode.py --output-dir outputs/q2/nonenergy_reproduce
python -B -X utf8 -m unittest discover -s tests -p test_q2_nonenergy.py -v
```

见[分账、结果和边界](solutions/p2-nonenergy-partition.md)。运行器验证冻结v2及源记录后执行全部29条路径，输出目录须不存在。168文件离线副本在两个固定依赖环境各37项产物完全一致；381项完整测试通过。部分碳账不能与旧GCB目标比较，未提供真实材料排放或全国S0验收。

### Q2 v11 部门终端能源与GDP响应

```powershell
python -B -X utf8 scripts/build_q2_sector_candidate.py
python -B -X utf8 scripts/run_q2_sector_candidate.py --output-dir outputs/q2/v11_reproduce
python -B -X utf8 scripts/run_q2_sector_diagnostics.py --output-dir outputs/q2/v11_sector_diagnostics_reproduce
```

两入口均要求新输出目录。全部756次训练和六条拒绝候选离线可重建；182文件副本在两环境数值/SVG一致，固定环境36项产物全同，另一环境仅PNG及其清单哈希不同。六种结构均选回原v10，不能因新分组而称全国校准完成。392项测试通过，详见[第十一轮报告](solutions/p2-iteration-v11.md)。
