# A题 · 多能源协同仿真研究工作区

以 `只读工作区/final.md` 为唯一研究主线。本工程已将 yx 的数学与数据准备、mmj 的可运行模块和证据核验、lb 的贸易及社会扩展资料按用途合并。仅研究 A 题。

**先看路线，再选数据，再运行。** 问题二全国聚合条件模型提供真实历史多目标校准、年度主体与连续运行、2030/2060条件推演和灵敏度，见[Q2候选与自检](docs/solutions/p2-lb.md)。官方统计衔接、逐厂状态及全年网络可靠性仍有限制，不能将研究候选称为官方预测；问题三进展和当前验收证据见下方P3入口。

2026-10-20：当前版本继续修复 review(9)，增加煤油气分项校准验收、官方类别衔接与动态统计桥回测，修正规划供给路径不一致、非化石优先调度遗漏和独立审查器变量覆盖错误。详见[本轮方法与范围](docs/solutions/p2-lb-review9-response.md)、[V10结构修复](docs/solutions/p2-lb-review10-structure.md)和[本轮实际结果](docs/solutions/p2-lb-review9-results.md)。V7 的257项测试、2250组训练等记录保存在[历史修复报告](docs/solutions/p2-lb-repaired.md)及归档中，不能作为新代码的通过证明。原误差门槛、已接触评估身份和团队审批要求保留。

**Q1 已由 PR #6 合并。** 合并 SHA 为 `804ec15ee43874303986a7ad91b2cde05c65b124`，采用 lb 主线及 mmj 补强。见[整合与逐项来源](docs/solutions/p1-yx-integration.md)和[完整报告](outputs/q1/p1_yx/report.md)。省级份额分母的31省来源血缘为保留的P3可选补强；本轮不改Q1原成果。

## 阅读入口

PR15 review(10) 的当前修复与复现方法见[跨运行数值等价及诊断接续](docs/solutions/p3-mmj-review10.md)。保留原模型、输入、政策与容差；新诊断默认 V3，旧 V5/V2 的测试和逐字节复现记录保留为历史证据。

P3/mmj 已完成问题三六情景、H01/H02、受约束政策筛选与敏感性；116个年度转型案例、两轮作者自查及独立目录复现均已完成，见[问题三V5方案与证据](docs/solutions/p3-mmj-v5.md)。当前结果为无可行政策、H02未观察到交互增量。其后已补齐[零进口、服务缺供与储能增排机制诊断](docs/solutions/p3-mmj-diagnostics.md)，新增实际对照与独立复现；最新检查见[专项验证汇总](outputs/validation/p3_mmj/diagnostics_validation_summary.json)，原339项测试保留为V5快照。完整配置使用 `workflow/q3_inputs_v5.json`，旧版本和失败证据保留；两位成员对最终SHA的评审仍未完成。

| 入口 | 用途 |
|---|---|
| [final 阅读版](docs/final_阅读版.md) | 完整最终方案，已适配118项文件引用；研究内容以只读原文为准 |
| [实施路线与缺口](docs/IMPLEMENTATION_ROADMAP.md) | 按final顺序衔接现有代码、数据和后续验收 |
| [数据使用与去重规则](docs/DATA_GUIDE.md) | 唯一记录、来源命名空间、已核验/候选/隔离及扩展门槛 |
| [运行说明](docs/RUNNING.md) | 环境、统一命令、局部成果的适用边界 |
| [整理验收报告](docs/ORGANIZATION_REPORT.md) | 文件去留、去重数量、保护与复现检查 |
| [创新备选阅读版](docs/gemini_final_idea_阅读版.md) | 基础主线验收后再启用的算法实验 |
| [三人 Git 协作规程](docs/17_git_collaboration.md) | 三人同题并行、Agent 开工、分支、PR、独立评审及合并 |
| [P0 → P1/Q1 开工单](docs/rounds/P0_P1_Q1.md) | 问题一的输入范围、交付物、验收与起跑线锁定状态 |
| [P1/lb 问题一候选](docs/solutions/p1-lb.md) | 本分支的问题一报告、补齐后逐项核对、用途审查与复现入口；尚未替代三人评审 |

## 目录职责

```text
A题/
├── 赛题PDF、附件1—4.xlsx       官方原件，保留根目录以兼容原核验契约
├── 只读工作区/               原方案与README，路径和字节均不改动
├── docs/                     当前指南、数学规格、来源说明及历史方案
├── data/
│   ├── raw/                  唯一原始文件与网页/PDF摘录
│   ├── extracted/            从原件提取的可检索文本
│   ├── observations/         mmj观测及限定用途子集，原证据契约不变
│   ├── processed/            结构化数据；lb/为补充表，unified/为去重视图
│   ├── catalog/              统一目录、来源映射、用途与冲突记录
│   └── restricted/           未纳入模型的家庭级/潜在细粒度材料
├── src/energy_model/          账本、资产、统计基线、原型和规则调度
├── scripts/                  处理、核验与执行程序
├── tests/                    原有约束与证据准入测试
├── workflow/                 原证据准入契约及final实施配置
├── examples/                 合成参数；不能作为真实中国输入
├── outputs/                  局部结果、历史审查及本次validation记录
├── apps/                     可选交互实验台
├── tools/legacy_lb/           保留的原采集/提取程序，经隔离入口重建
├── prompts/                  带final优先约束的阶段提示
└── archive/                  文件去留凭据、变更前原文与诊断记录
```

`docs/history/` 中旧基年、情景编号与研究优先级仅作追溯；执行以final为准。`tmp/` 仅由运行时产生，不是数据或交付成果。原三人工作区已不再作为并行工程保留。

## 常用命令

`run.py q2` 默认执行本分支全国聚合条件模型，写入 `outputs/q2/p2_lb_national/`。工程夹具需显式指定 `--config examples/q2/config.json`；首轮候选盘点/拒绝演示保留在 `workflow/q2_inputs.json`，不再是默认入口。共同起点为用户指定的 `804ec15ee43874303986a7ad91b2cde05c65b124`，尚不替代其他两人的交叉评审。

在本目录用 Python 3.11 及以上运行（本轮复现环境记录在 `outputs/validation/`）：

```powershell
python -B -X utf8 run.py audit          # 原件、文件去留、链接、去重及隔离检查
python -B -X utf8 scripts/scan_google_keys.py # 扫描工作树及 ZIP 内的 Google API key
python -B -X utf8 run.py test           # 全部现有测试，实际数量见validation结果
python -B -X utf8 run.py q1 --output-dir outputs/q1/p1_yx # lb主线与mmj补强；先安装requirements-q1.txt
python -B -X utf8 run.py q2             # 全国聚合条件模型；先安装requirements-q2.txt
python -B -X utf8 scripts/review_q2_national_delivery.py # 独立进程复现及第二次自检
python -B -X utf8 run.py attachments    # 官方附件标准化，保留890条记录及重复组
python -B -X utf8 run.py verify         # 准入检查及限定初评/需求回算/许可案例
python -B -X utf8 run.py prototype      # 合成年度主体及连续储能窗口
python -B -X utf8 run.py catalog        # 重建来源、数据目录及统计局唯一记录视图
python -B -X utf8 run.py reproduce-lb --recipe trade
```

原 `run_*.ps1` 入口继续可用。图形界面另装 `requirements-workbench.txt`；主线数据核验不依赖界面。完整说明见[运行指南](docs/RUNNING.md)。

## 固定研究约束

- 候选初态2024年；2023细账、2025更新分存。历史训练2015—2021，评估2022—2024，明确为已接触留出。
- 首批S0/SP/SG/ST，其后SW/SGW；H01/H02为主实验，AI、居民和就业按数据门槛扩展。
- 官方附件是项目样本，不能外推为同期全国电厂清单；同名项保留，不能按电厂名称盲目删行。
- 相同来源仅计一条观测。不同统计期、单位、版本、地域及边界保留区别；缺失不填零，冲突不取平均。
- 世界银行争议价格、候选输电线路继续隔离。合成EU/SU/CU不得直接改名为物理量或人民币。
- 缺少完整全国净排放与移除路径时，不输出全国碳中和结论。
