# 运行与复现

## 当前问题二答案入口（2026-10-20）

当前主答案使用 `scripts/run_q2_portable.py --verify-reference` 重算24组问题二实验；从原件解析使用 `scripts/run_q2_current_delivery.py --only S0 --workers 1`。安装依赖、结果目录和边界见[问题二交付说明](solutions/QUESTION2_DELIVERY_20261020.md)。`run.py q2` 保留 PR #9 旧模型入口，不代表本次新答案。下方较早实验命令保留作研究追溯；本次PR只携带最终问题二复现所需结果，其他探索结果保留在作者研究工作区。


2026-10-20新增新机效率与项目竞争版本，默认入口尚未替换。已保存原件时可离线运行：

```powershell
python -B -X utf8 scripts/run_q2_thermal_pairs.py outputs/q2_revenue_recalibration/20261019T225922280430Z
python -B -X utf8 scripts/run_q2_project_competition_pairs.py
python -B -X utf8 scripts/run_q2_thermal_coal_window.py
python -B -X utf8 scripts/run_q2_competition_coal_window.py
python -B -X utf8 scripts/run_q2_thermal_recalibration.py --design workflow/q2_thermal_net55_recalibration.json --workers 2
python -B -X utf8 scripts/run_q2_thermal_recalibration.py --design workflow/q2_thermal_net58_recalibration.json --workers 2
```

固定参数对照使用程序中明确锁定的历史父目录，并逐项核对哈希；没有默认为最新目录。两种效率与三组承诺条件全部保留。最后两条是统一业主热机对照训练，不能当作竞争模型已经重训。520项全量测试收据和已完成实验见[本轮说明](solutions/q2_project_competition_round_20261020.md)。

2026-10-20新增历史煤价动态诊断（原件存在时离线运行）：

```powershell
python -B -X utf8 scripts/collect_q2_coal_prices_extension.py
python -B -X utf8 scripts/run_q2_fuel_price_diagnostic.py outputs/q2_revenue_recalibration/20261019T225922280430Z
python -B -X utf8 scripts/run_q2_coal_index_window.py outputs/q2_revenue_recalibration/20261019T225922280430Z
python -B -X utf8 scripts/diagnose_q2_new_thermal_efficiency.py outputs/q2_coal_index_window/20261019T233144607111Z
```

前两项动态运行生成新时间目录；最后一项参数应换成实际五年对照目录。税基未知和共用市场代理限制必须保留；效率诊断固定原路径，不能称新增项目已批准。见[煤价与效率核查](solutions/q2_fuel_price_round_20261020.md)。

当前 Q1 采用 lb 主线与 mmj 增量整合，详见[整合说明](solutions/p1-yx-integration.md)。`python -B -X utf8 run.py q1` 默认写入 `outputs/q1/p1_yx/`，保留 lb 原候选产物。完整交付核验仍运行 `python -B -X utf8 scripts/review_q1_delivery.py`，本次证据写入 `outputs/q1_review/lb_mmj_integration/`；其中两次 Q1 分别写入 `p1_yx`、`yx_reproduction`。显式重建 `scripts/prepare_q1_review.py` 会重新核对 mmj 已用 IRENA 原文再重建六条成本参数，并拒绝未经重新审查的 lb 原输入变化。

在A题目录执行。Python 3.11及以上；本轮使用本机捆绑Python 3.12.14。核心模型和测试主要使用标准库；附件需要openpyxl，yx/lb离线提取需要pandas/numpy/lxml/pypdf/pdfplumber。

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-data.txt
.\.venv\Scripts\python -B -X utf8 run.py audit
.\.venv\Scripts\python -B -X utf8 run.py test
```

新环境安装命令供迁移到其他机器时使用。通用依赖记录见 `outputs/validation/environment.json`；全国聚合条件模型已接入Mesa/SciPy，其实际冻结版本与验收见 `outputs/q2_review/p2_lb_national/verification.json`。旧 `.venv-workbench` 不作为数据或提交材料。

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

`docs/solutions/p1-yx-integration.md`为当前入口，记录两份已通过本地技术复审的候选采用关系；本次完整整合PR须由mmj、lb对同一最终提交正式评审。原lb报告与产物作为历史交付保留。

## 可选界面

```powershell
.\.venv\Scripts\python -m pip install -r requirements-workbench.txt
.\run_workbench.ps1 -PythonPath .\.venv\Scripts\python.exe
```

界面依赖清单沿用原mmj版本。操作手册与截图保留；本次整理以命令行数据/模块复现为验收，未宣称重新完成浏览器交互验收。界面仍显示合成实验和局部证据，不能当全国预测演示。

## P2/lb 全国聚合条件模型

**2026-10-20状态补充：下述V10默认入口保留作历史追溯，不代表收入/补贴及统计边界修订后的正式答题模型。** 当前修订分支使用下列独立入口，避免覆盖历史结果。使用既有 `requirements-q2.txt` 与 `requirements-data.txt`；PDF可视核读另用pypdfium2 5.14.0。

```powershell
python -B -X utf8 scripts/run_q2_revenue_recalibration.py --design workflow/q2_exposure_recalibration.json
python -B -X utf8 scripts/run_q2_joint_recalibration.py --workers 4
python -B -X utf8 scripts/review_q2_joint_search.py outputs/q2_revenue_recalibration/<联合训练时间戳>
python -B -X utf8 scripts/collect_q2_solar_entitlement.py
python -B -X utf8 scripts/run_q2_solar_entitlement.py outputs/q2_revenue_recalibration/<联合训练时间戳>
python -B -X utf8 scripts/review_q2_revenue_candidate.py outputs/q2_solar_entitlement/<资格修正时间戳>
python -B -X utf8 scripts/review_q2_revenue_candidate.py outputs/q2_revenue_recalibration/<该次时间戳>
python -B -X utf8 scripts/diagnose_q2_fit_drivers.py outputs/q2_revenue_recalibration/<该次时间戳>
python -B -X utf8 scripts/run_q2_exposure_sensitivity.py outputs/q2_revenue_recalibration/<该次时间戳>
python -B -X utf8 scripts/run_q3_paired_snapshot.py outputs/q2_revenue_recalibration/<该次时间戳>
python -B -X utf8 scripts/build_q3_gas_evidence.py
python -B -X utf8 scripts/run_q3_supply_boundary.py outputs/q2_revenue_recalibration/<该次时间戳>
python -B -X utf8 scripts/run_q3_frozen_response.py outputs/q3_supply_boundary/<上一条输出的时间戳>
```

时间戳使用相应上一步实际输出的目录名。历史重新训练309个条件候选，三个承诺额度各自按2015—2021选择，然后才运行2022—2024已接触评估，保留全部三组及市政机制对照；没有选择误差最小的承诺额度。审查会拒绝来源或代码已变化的旧实验。Q3入口首先重现同一历史候选；气源入口报告全部六种气源/期末库存边界共24次连续配对。冻结入口核验保存设计和快照，以独立动作不等式固定气电增发上限，再报告另外24次对照的绝对缺供与交互变化。这是指定短期H02渠道实验，不是正式全国情景验收或完整长期H02。总体完成情况见[持续核对](rounds/ANSWER_READY_AUDIT.md)，政府支持覆盖情况见[专项说明](solutions/government_support_status.md)。

2026-10-20后续：联合搜索另有717个实际唯一候选，完整范围/顺序/损失/择优独立审计见`outputs/q2_revenue_recalibration/20261019T223517292100Z/search_review.json`。它用先前完整训练作起点，不覆盖原309次研究。20年资格工厂通过现有政策接口配置，不修改旧研究源码；政策对照固定各组既有参数、共六案，不能称为重新训练。新取得官方原件先核验再登记；`collect_q2_solar_entitlement.py`在原件已存在时离线核验，不覆盖或自动刷新原件哈希。需求趋势失败试验可用`diagnose_q2_nonpower_trend.py`复现，未迁移系统模型。

安装 `requirements-q2.txt`，数据审查和Q1回归还需已有的 `requirements-data.txt`、`requirements-q1.txt`。当前实测环境为Python3.12、Mesa3.3.1、SciPy1.16.3，原环境不自动升级依赖。

```powershell
python -B -X utf8 scripts/build_q2_national_inputs.py
python -B -X utf8 run.py q2
python -B -X utf8 scripts/review_q2_delivery.py
python -B -X utf8 scripts/review_q2_national_delivery.py
```

第一条按26项已审查原件/参考重建511条观测、技术参考、GCB条件峰值与统计类别专项审查，不变更原Q1契约。第二条执行1012次交替有限网格训练、已接触评估、独立2024初态及条件试验；不宣称全联合网格最优。结果见 `outputs/q2/p2_lb_national/`。第三条保留工程夹具和原Q1回归，包括故意拒绝未准入首轮配置的测试；其旧状态名称 `engineering_passed_national_blocked` 仅指这个旧配置，不能替代第四条的全国候选验收结论。第四条执行独立进程、不同哈希种子的完整训练和推演复现，以及来源/结果/账本/失败语义核查。拟合不合格时仍完成独立复现并返回失败，不能把执行成功当科学验收通过。

当前结果入口为[review(9)修复结果](solutions/p2-lb-review9-results.md)。`fuel_share_validation.csv`覆盖煤油气及两个基线；`generation_validation.csv`覆盖八种发电技术；`demand_identification.json`记录仅由训练数据识别的条件非电需求，V10方法见[结构修复](solutions/p2-lb-review10-structure.md)；`statistical_bridge_backtest.csv`隔离统计转换误差。后续交叉检查入口为 `scripts/check_q2_repaired_mechanisms.py` 和 `scripts/check_q2_2025_extension.py`；2025观测不参与选参。

V7统一Issue #7共同入口：`python -B -X utf8 run.py q2 --config workflow/q2_inputs.json --output-dir outputs/q2/review_pr9_common_entry`。该配置名为明确提示的兼容别名，实际使用全国专用设计及用途审查；`q2_inputs.json`原字节和候选用途不升级。若仅检查旧候选清单，用`python scripts/run_q2.py --config workflow/q2_inputs.json`，仍按旧契约阻断。独立复现使用共同配置入口。

每次运行保留旧输出于同名 `.attempts/`；`latest-attempt.json`决定当前有效性。先前成功不能掩盖新失败。读取全国结果前调用 `scripts/run_q2_national.py` 中的 `verify_latest`，核对当前代码、输入、原件和全部结果哈希。`q2_scientific_complete=false` 是执行器不自行签发研究验收的约定；四任务交付结论见独立审查的 `outputs/q2_review/p2_lb_national/verification.json`，不代表团队批准。

复现只承诺冻结假设内的确定性结果；碳排放留出缺测、统计桥接、代表日和反复使用评估窗口的限制见[模型修订记录](solutions/p2-lb-national-review.md)。

## 版本与恢复

2026-10-20后续修正入口（历史验证和Q3统一使用光伏资格＋独立投资审核工厂）：

```powershell
python -B -X utf8 scripts/run_q2_corrected_recalibration.py --workers 4
python -B -X utf8 scripts/review_q2_joint_search.py outputs/q2_revenue_recalibration/20261019T225922280430Z
python -B -X utf8 scripts/run_q2_corrected_followups.py timing outputs/q2_revenue_recalibration/20261019T225922280430Z
python -B -X utf8 scripts/run_q2_corrected_followups.py snapshot outputs/q2_revenue_recalibration/20261019T225922280430Z
python -B -X utf8 scripts/run_q2_corrected_followups.py boundary outputs/q2_revenue_recalibration/20261019T225922280430Z
python -B -X utf8 scripts/run_q3_frozen_response.py outputs/q3_supply_boundary/20261019T230931220030Z
python -B -X utf8 scripts/collect_q2_coal_prices.py
python -B -X utf8 scripts/diagnose_q2_coal_price.py outputs/q2_revenue_recalibration/20261019T225922280430Z
```

新运行会生成新时间目录，后续参数改为该实际目录。旧后续脚本直接调用旧工厂，修正版历史必须使用`run_q2_corrected_followups.py`；适配器在运行记录中声明工厂和源哈希，且核对历史逐项复现。电煤原件已存在时离线核查；价格会计诊断不改变系统价格或投资轨迹。详见[本轮实际结果](solutions/q2_corrected_round_20261020.md)。

`archive/organization_20261017/file_disposition.csv` 逐文件记录旧路径→新位置或删除理由。修改过的文档/脚本原字节保存在 `edited_originals.zip`；复算前的结果与目录在 `prior_results.zip`。恢复时按该映射提取单个文件，不把全部旧目录覆盖回当前工程。
