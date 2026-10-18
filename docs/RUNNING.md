# 运行与复现

## Q1 候选研究入口（p1/mmj）

`python -B -X utf8 run.py q1 --output-dir outputs/q1/p1_mmj`离线生成历史、指标、12类角色、Q2交接、缺口、静态账、图文报告和运行manifest。评审使用独立目录`outputs/q1/review_mmj`。缺输入、指纹/口径错误返回非零；无归属目录不覆盖。正常运行的可安装依赖见`requirements-q1.txt`，固定matplotlib 3.10.8；核心计算使用标准库。实质证据重建脚本`prepare_q1_inputs.py`另需`requirements-data.txt`中的openpyxl、pypdf、lxml，不在常规复现中隐式调用。

仅复跑已提交的Q1输入和图表时：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-q1.txt
.\.venv\Scripts\python -B -X utf8 run.py q1 --output-dir outputs/q1/review_mmj
```

CSV/JSON/Markdown为科学结果比较依据，同代码、输入、配置下应逐字节一致。PNG另受matplotlib、NumPy、Pillow、FreeType等渲染依赖影响；固定顶层版本不构成跨平台PNG字节保证。同一环境应一致，跨环境应核对科学数据和图形含义；每次manifest记录实际matplotlib及渲染依赖版本。

本项目按原件与处理表字节核验。新克隆在首次签出前关闭换行转换；已有干净工作区更新前同样检查本地设置，不对带哈希原件批量规范化：

```powershell
git -c core.autocrlf=false clone https://github.com/Shoufves/SimulationModelingProblemA.git
# 已有仓库在其目录中执行
git config --local core.autocrlf false
```

本轮撤回候选新增的`.gitattributes`，依协作文档§6.4将仓库换行属性统一留待专门PR评审。

见[候选说明](solutions/p1-mmj.md)。四维结果各有限定范围，不宣称全国校准或Q2准入完成。默认审计对`data/restricted`只验证存在/大小，密钥扫描剪枝私有内容与环境/临时缓存；结果明确披露排除范围。官方附件及只读原文仍逐字节核验。

在A题目录执行。Python 3.11及以上；本轮使用本机捆绑Python 3.12.14。核心模型和测试主要使用标准库；附件需要openpyxl，yx/lb离线提取需要pandas/numpy/lxml/pypdf/pdfplumber。

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-data.txt
.\.venv\Scripts\python -m pip install -r requirements-q1.txt
.\.venv\Scripts\python -B -X utf8 run.py audit
.\.venv\Scripts\python -B -X utf8 run.py test
```

完整数据准备使用上面两份依赖，Q1常规复跑只需Q1清单。整理阶段的实际环境见 `outputs/validation/environment.json`；本轮评审修复的干净安装及两轮自检证据另见`docs/reviews/q1-mmj-review-fixes-20261018.md`。旧 `.venv-workbench` 已移除，不作为数据或提交材料。未来Mesa/SciPy正式模型尚未实现，不能据现有依赖清单宣称全国模型环境已验收。

| 命令 | 做什么 | 输出/边界 |
|---|---|---|
| `python -B -X utf8 run.py audit` | 检查原件、保留记录、原文备份、final引用、语法、唯一键及隔离 | outputs/validation/workspace_audit.json |
| `python -B -X utf8 run.py test` | 既有测试及Q1计算/反例/契约测试 | outputs/validation/tests.json；数量以实际执行为准，不替代科学验证 |
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

## 可选界面

```powershell
.\.venv\Scripts\python -m pip install -r requirements-workbench.txt
.\run_workbench.ps1 -PythonPath .\.venv\Scripts\python.exe
```

界面依赖清单沿用原mmj版本。操作手册与截图保留；本次整理以命令行数据/模块复现为验收，未宣称重新完成浏览器交互验收。界面仍显示合成实验和局部证据，不能当全国预测演示。

## 版本与恢复

`archive/organization_20261017/file_disposition.csv` 逐文件记录旧路径→新位置或删除理由。修改过的文档/脚本原字节保存在 `edited_originals.zip`；复算前的结果与目录在 `prior_results.zip`。恢复时按该映射提取单个文件，不把全部旧目录覆盖回当前工程。
