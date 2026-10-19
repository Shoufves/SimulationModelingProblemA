# A题 · 多能源协同仿真研究工作区

问题二交流入口：[P2/yx 阶段性 Draft](docs/solutions/p2-yx-draft.md)。本次分享工程闭环和截至 v13 的历史诊断，全国模型与预测尚未验收；供与其他成员方案比较补强。

2026-10-19 当前状态见 [v13 审批与需求联合校准](docs/solutions/p2-iteration-v13.md)：653 次训练、423 项测试通过；风电留出 MAPE 降至 6.57%，但煤、油、气、光及 CO₂ 代理共五项失败，六组全国输入、S0 和全国灵敏度尚未完成。

输入与机制补强另见 [2024 初态核对](docs/solutions/p2-current-state-2024.md)及[终端服务与设备替代](docs/solutions/p2-device-service-mapping.md)；历次结果均保留原适用边界。

以 `只读工作区/final.md` 为唯一研究主线。本工程已将 yx 的数学与数据准备、mmj 的可运行模块和证据核验、lb 的贸易及社会扩展资料按用途合并。仅研究 A 题。

**先看路线，再选数据，再运行。** 当前能够复现附件处理、限定数据初评、需求统计回算、许可案例与合成机制实验。Q2已实现年度与运行层耦合，并完成十三轮真实历史聚合诊断及五轮各27组历史配对响应；当前候选五项质量门槛仍失败，尚未完成全国校准验收、2030/2060预测及政策优化。整理或工程测试通过不等于研究完成。

**Q1 已整合并合入 main：lb 主线、mmj 补强。** PR #6 的评审 head 为 `da8a983`，squash 合并提交为 `804ec15ee43874303986a7ad91b2cde05c65b124`；用户明确确认三人同意并授权合并，正式 reviews 留痕的例外见[轮次日志](docs/ROUND_LOG.md)。见[整合与逐项来源](docs/solutions/p1-yx-integration.md)和[完整报告](outputs/q1/p1_yx/report.md)。默认 `run.py q1` 写入 `outputs/q1/p1_yx/`。问题二已在 Issue #7 标为开发进行中，共同 base 为 `804ec15ee43874303986a7ad91b2cde05c65b124`；文档 PR #8 并行评审。本地进度与未完成项见 [P2/yx](docs/solutions/p2-yx.md)，较早的[开工单](docs/rounds/P2_Q2.md)准备状态保留为当时快照。

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
| [轮次日志](docs/ROUND_LOG.md) | 问题一采用关系、合并、验收、延期项及下一轮状态 |
| [P2/Q2 开工单](docs/rounds/P2_Q2.md) | 问题二完整任务、输入用途、必交产物、验收与待锁定基线 |
| [P2/yx 本地实现进展](docs/solutions/p2-yx.md) | 用户授权后的 Mesa/SciPy 闭环、历史用途复核、工程复现与未完成项；不等于全国验收 |
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

此前[第七轮建设约束对照](docs/solutions/p2-iteration-v7.md)选中原结构，保留五项失败。此前补入[能源账桥接与部门初态约束](docs/solutions/p2-balance-bridge.md)：煤炭15项聚合吻合、APEC2014详细平衡及缺项区间已离线复算。另补[2015核电许可/容量/开工状态](docs/solutions/p2-nuclear-reference.md)，8台额定8980MWe及两处编号冲突已核验。[v8核电审批回放](docs/solutions/p2-iteration-v8.md)使核电项通过原门槛，仍有四项失败；最新[v9风光联合校准](docs/solutions/p2-iteration-v9.md)完成486组训练，训练改善但风电留出恶化；另有[历史电价时间线](docs/solutions/p2-policy-timeline.md)补核。另完成[名义合同有限批次对照](docs/solutions/p2-nominal-contracts.md)：七条路径财政支付有变化，物理路径未改善；其后[v10初始光伏队列联合诊断](docs/solutions/p2-iteration-v10.md)完成1458组训练，四项门槛仍失败；另补[2024核电设备与队列参照](docs/solutions/p2-nuclear-state-2024.md)，源内身份/时点冲突保留；另完成[活动量驱动及交通口径复审](docs/solutions/p2-activity-drivers.md)，其后完成[非能源原料分账试验](docs/solutions/p2-nonenergy-partition.md)：29条预设路径、原料/燃料/现金核对及两环境37项产物复现通过。其后[v11部门需求诊断](docs/solutions/p2-iteration-v11.md)完成756次训练，六种结构均保留原控制；新的部门统一GDP响应没有改善训练。当前392项测试通过，全国预测尚未验收。

在本目录用 Python 3.11 及以上运行（本轮复现环境记录在 `outputs/validation/`）：

```powershell
python -B -X utf8 run.py audit          # 原件、文件去留、链接、去重及隔离检查
python -B -X utf8 scripts/scan_google_keys.py # 扫描工作树及 ZIP 内的 Google API key
python -B -X utf8 run.py test           # 全部现有测试，实际数量见validation结果
python -B -X utf8 run.py q1 --output-dir outputs/q1/p1_yx # lb主线与mmj补强；先安装requirements-q1.txt
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
