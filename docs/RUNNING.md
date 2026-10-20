# 运行与复现

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

## P3/yx 问题三

先安装 `requirements-q3.txt`（推荐Python3.12），从仓库根目录执行：

```powershell
python -B -X utf8 run.py q3 --config workflow/q3_inputs.json --output-dir outputs/q3/p3_yx
python -B -X utf8 scripts/review_q3_delivery.py
python -B -X utf8 run.py q3 --config workflow/q3_inputs.json --output-dir outputs/q3/p3_yx_reproduction
python -B -X utf8 scripts/compare_q3_runs.py
python -B -X utf8 scripts/probe_q3_retirement.py
python -B -X utf8 scripts/review_pr13_changes.py
python -B -X utf8 scripts/summarize_q3_evidence.py
```

全部实验离线执行，默认最多4进程，可设环境变量 `Q3_WORKERS=1` 串行。新尝试先使旧收据失效；失败返回非零并保留旧尝试。原问题二模块只增加非循环窗口的可选自由终端SOC，原默认行为有完整回归。科学范围、成本及资金、选参和检验边界见 [P3报告说明](solutions/p3-yx.md)。重复复现输出和失败尝试不重复提交，验收记录及必要失败证据保留。

原v3主批次实际约16.3分钟、独立完整复现约21.4分钟；PR13修复后的耗时以新manifest为准，硬件和并发会改变耗时。Q1/Q2回归分别使用独立输出目录`outputs/q1/q3_yx_regression`和`outputs/q2/q3_yx_regression`，运行后执行`python -B -X utf8 scripts/review_q3_regressions.py --q2`核对原产物和受保护文件。Q2回归会完整重做1012次训练及107项条件试验，需要额外时间。

本次PR13仅修正Q3退役分类和L说明，实际重新执行完整测试与两套Q3，Q1/Q2沿用原完整回归并重新核验依赖和产物；作用域收据由 `scripts/review_pr13_regression_scope.py` 生成。不能将依赖核验说成重新训练。修复前后比较需要本地保留原提交 `bf8590809004466d2f595407eb61ddd2b6b7e5a2`，若浅克隆缺失须先取得该提交。新增到龄量只覆盖受Q3计划管理的退出，定义和L作用对象表见[审查回应](solutions/p3-pr13-review-response.md)。

`outputs/q3_review/README.md`列出本次证据与复跑步骤。`scripts/accept_q3_delivery.py`只汇总已执行且指纹匹配的本地证据；不能用它替代前述实际运行或两位成员的C9批准。

## Q1/Q3补充研究审查

本轮只读取既有科学产物，新增来源暴露、实施等价类、Shapley与文本诊断。使用已有Q3环境及openpyxl，从仓库根目录运行：

```powershell
python -B -X utf8 scripts/audit_q1_q3_research.py
$env:PYTHONHASHSEED='29'
python -B -X utf8 scripts/audit_q1_q3_research.py --output-dir outputs/research_audit/q1_q3_reproduction
python -B -X utf8 scripts/verify_q1_q3_audit.py --run-checks
```

两套诊断结果写不同目录，最后一条实际运行全部测试、基础审计、正式输入检查和密钥格式扫描，再比较诊断输出与指纹。不带`--run-checks`只核验已有且指纹匹配的检查收据，不冒称重跑测试。原`outputs/validation`与`outputs/workflow`的被跟踪文件在保存本轮证据后恢复到执行前字节，验收证据独立保存在`outputs/research_audit/verification`。

诊断的`--science-only`是局部探索模式；即使正常执行，其manifest的`passed`仍为false，不作为完整验收。正式诊断会检查24组论文关键数值及原科学资产与起点`7d52f439992503eac5978c6f218f5289fe3e2195`字节相同；浅克隆须包含该提交。输出目录必须专用。新文稿或证据登记改变后需重新运行，不能只重写哈希。

此轮没有重新求解全部Q3或训练Q2，而是在原依赖与科学产物未变的前提下复用上一轮完整复现，再独立重做本轮分析。科学解释、外部检测和人工批准分开记录，技术通过不替代人工签认。文献采用离线书目登记，访问限制已列明；复跑不会自动访问检测平台或补签团队批准。

## 版本与恢复记录（原工作区整理）

`archive/organization_20261017/file_disposition.csv` 逐文件记录旧路径→新位置或删除理由。修改过的文档/脚本原字节保存在 `edited_originals.zip`；复算前的结果与目录在 `prior_results.zip`。恢复时按该映射提取单个文件，不把全部旧目录覆盖回当前工程。
