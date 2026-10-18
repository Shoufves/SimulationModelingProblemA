# 运行与复现

当前 Q1 采用 lb 主线与 mmj 增量整合，详见[整合说明](solutions/p1-yx-integration.md)。`python -B -X utf8 run.py q1` 默认写入 `outputs/q1/p1_yx/`，保留 lb 原候选产物。完整交付核验仍运行 `python -B -X utf8 scripts/review_q1_delivery.py`，本次证据写入 `outputs/q1_review/lb_mmj_integration/`；其中两次 Q1 分别写入 `p1_yx`、`yx_reproduction`。显式重建 `scripts/prepare_q1_review.py` 会重新核对 mmj 已用 IRENA 原文再重建六条成本参数，并拒绝未经重新审查的 lb 原输入变化。

在A题目录执行。Python 3.11及以上；本轮使用本机捆绑Python 3.12.14。核心模型和测试主要使用标准库；附件需要openpyxl，yx/lb离线提取需要pandas/numpy/lxml/pypdf/pdfplumber。

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-data.txt
.\.venv\Scripts\python -B -X utf8 run.py audit
.\.venv\Scripts\python -B -X utf8 run.py test
```

新环境安装命令供迁移到其他机器时使用。本轮未重新安装依赖；精确实际版本见 `outputs/validation/environment.json`。旧 `.venv-workbench` 已移除，不作为数据或提交材料。未来Mesa/SciPy正式模型尚未实现，不能据现有依赖清单宣称全国模型环境已验收。

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

第一条按原图复核转录、原始API/CSV和报告页表重建511条观测及技术参考，不变更原Q1契约。第二条执行216组训练搜索、已接触评估、独立2024初态及条件试验；结果见 `outputs/q2/p2_lb_national/`。第三条保留工程夹具和原Q1回归，包括故意拒绝未准入首轮配置的测试；其旧状态名称 `engineering_passed_national_blocked` 仅指这个旧配置，不能替代第四条的全国候选验收结论。第四条执行独立进程、不同哈希种子的复现及来源/结果/账本/失败语义核查。

每次运行保留旧输出于同名 `.attempts/`；`latest-attempt.json`决定当前有效性。先前成功不能掩盖新失败。读取全国结果前调用 `scripts/run_q2_national.py` 中的 `verify_latest`，核对当前代码、输入、原件和全部结果哈希。`q2_scientific_complete=false` 是执行器不自行签发研究验收的约定；四任务交付结论见独立审查的 `outputs/q2_review/p2_lb_national/verification.json`，不代表团队批准。

复现只承诺冻结假设内的确定性结果；碳排放留出缺测、统计桥接、代表日和反复使用评估窗口的限制见[模型修订记录](solutions/p2-lb-national-review.md)。

## 版本与恢复

`archive/organization_20261017/file_disposition.csv` 逐文件记录旧路径→新位置或删除理由。修改过的文档/脚本原字节保存在 `edited_originals.zip`；复算前的结果与目录在 `prior_results.zip`。恢复时按该映射提取单个文件，不把全部旧目录覆盖回当前工程。
