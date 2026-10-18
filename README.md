# A题 · 多能源协同仿真研究工作区

以 `只读工作区/final.md` 为唯一研究主线。本工程已将 yx 的数学与数据准备、mmj 的可运行模块和证据核验、lb 的贸易及社会扩展资料按用途合并。仅研究 A 题。

**先看路线，再选数据，再运行。** 当前能够复现附件处理、限定数据初评、需求统计回算、许可案例与合成机制实验。全国多智能体历史校准、年度与运行层耦合、2030/2060预测及政策优化仍需实施；整理完成不等于这些研究已完成。

## 阅读入口

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
| [P1/mmj Q1 候选研究](docs/solutions/p1-mmj.md) | 四项研究、四维诊断、能源角色、静态核对和Q2候选交接；待两人评审 |

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

在本目录用 Python 3.11 及以上运行（本轮复现环境记录在 `outputs/validation/`）：

```powershell
python -B -X utf8 run.py audit          # 原件、文件去留、链接、去重及隔离检查
python -B -X utf8 scripts/scan_google_keys.py # 扫描工作树及 ZIP 内的 Google API key
python -B -X utf8 run.py test           # 全部既有测试和Q1反例验证
python -B -X utf8 run.py attachments    # 官方附件标准化，保留890条记录及重复组
python -B -X utf8 run.py verify         # 准入检查及限定初评/需求回算/许可案例
python -B -X utf8 run.py prototype      # 合成年度主体及连续储能窗口
python -B -X utf8 run.py catalog        # 重建来源、数据目录及统计局唯一记录视图
python -B -X utf8 run.py reproduce-lb --recipe trade
python -B -X utf8 run.py q1 --output-dir outputs/q1/p1_mmj # Q1研究候选，保留缺口
```

原 `run_*.ps1` 入口继续可用。图形界面另装 `requirements-workbench.txt`；主线数据核验不依赖界面。完整说明见[运行指南](docs/RUNNING.md)。

Q1使用`workflow/q1_inputs.json`登记的本地输入与matplotlib，不隐式联网。评审改输出目录为`outputs/q1/review_mmj`，不覆盖其他方案或无归属目录。2021—2024价格版本、2024储能初态、网络时序和独立物理碳核对等缺口仍阻断，不代表全国初始化或校准完成。默认扫描和审计不打开`data/restricted`内容；审计仅查其存在和大小，未证明其内容哈希不变。

## 固定研究约束

- 候选初态2024年；2023细账、2025更新分存。历史训练2015—2021，评估2022—2024，明确为已接触留出。
- 首批S0/SP/SG/ST，其后SW/SGW；H01/H02为主实验，AI、居民和就业按数据门槛扩展。
- 官方附件是项目样本，不能外推为同期全国电厂清单；同名项保留，不能按电厂名称盲目删行。
- 相同来源仅计一条观测。不同统计期、单位、版本、地域及边界保留区别；缺失不填零，冲突不取平均。
- 世界银行争议价格、候选输电线路继续隔离。合成EU/SU/CU不得直接改名为物理量或人民币。
- 缺少完整全国净排放与移除路径时，不输出全国碳中和结论。
