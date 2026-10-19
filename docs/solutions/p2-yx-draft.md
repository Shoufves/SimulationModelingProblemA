# P2/yx 阶段性 Draft：年度运行闭环与 v13 历史诊断

本次提交供三人交流和比较方案，关联 Issue #7；尚未完成全国模型准入、校准、2030/2060 S0 和全国灵敏度，不请求作为完整 Q2 方案验收或关闭任务。

共同 base 为 `804ec15ee43874303986a7ad91b2cde05c65b124`。本实现从其后的准备文档提交 `af93075` 延续开发；文档 PR #8 与开发并行，不改变共同起点。本 PR 不合并其他成员候选，也不代替成员批准。

## 建议队员先读

1. [整体实现与历史进展](p2-yx.md)：七类年度主体、投资/资金/许可队列、LP/MILP 运行、能碳现金账、失败语义及输入参照。
2. [最新 v13 实验](p2-iteration-v13.md)：审批分配与需求联合校准，训练选择、同一模型的八项留出结果及复现容差。
3. [2024 初态资料](p2-current-state-2024.md)与[终端服务/设备替代](p2-device-service-mapping.md)：哪些是已核原件，哪些仍是代理或研究假设。
4. [全国入口缺口](../../workflow/q2_inputs.json)及[作者建议验收配置](../../workflow/q2_acceptance.json)：六组输入尚未准入；阈值不冒充题面要求或三人共识。
5. `outputs/q2/historical_candidate_v13/` 的训练选择、质量结果、所选模型和完整账本，以及 `outputs/q2/allocation_checks.json`。

## 当前能提供什么

保留年度→队列→连续运行→账本→下一年度闭环、建设资金承诺和时滞、共享燃料、储能 SOC 及互斥、分时估值与财政/资源成本分账；原 Q1 代码和成果继续保留。历史资料、具体用途、冲突与缺失均单独记录。

v13 主实验执行 653 次训练，主实验累计 6648 次（含控制和有限差分，非独立样本数）。选择只按 2015—2021 训练，2022—2024 已接触留出单列。风电留出 MAPE 改善至约 6.57%；煤、油、气、光伏及有效 CO₂ 代理五项仍失败。不能把历轮最优单项拼成一个通过模型。

工程入口可执行，但使用合成夹具；正式全国入口目前应返回非零并列明六组缺口。历史候选的条件响应和工程至 2060 路径不能冒充全国 S0 或全国灵敏度。

## 可重复检查

从仓库根目录安装依赖；逐包锁定版本见 `requirements-q2-lock.txt`，可选旧表提取依赖见 `requirements-q2-data.txt`。开发环境为 Python 3.13。

```powershell
python -m pip install -r requirements-q2.txt
python -B -X utf8 run.py test
python -B -X utf8 run.py audit
python -B -X utf8 scripts/scan_google_keys.py
python -B -X utf8 scripts/workflow_status.py --check-formal-inputs
python -B -X utf8 scripts/check_q2_allocation.py
python -B -X utf8 scripts/check_q2_device_mapping.py
# 使用新输出目录；这仅验证工程夹具
python -B -X utf8 run.py q2 --config examples/q2_engineering.json --output-dir outputs/q2/reviewer_engineering
# 此正式入口当前预期拒绝未准入输入，不能记为全国运行成功
python -B -X utf8 run.py q2 --config workflow/q2_inputs.json --output-dir outputs/q2/reviewer_national
```

如需完整重跑 v13，按其专用报告使用新目录执行冻结配置；本次发布核对不重新计入历史训练次数。发布快照的实际检查见 `outputs/q2_review/draft_preflight_20261019.json`。

## 希望共同比较的补强点

- 与其他方案（包括 lb PR #9）逐项比较同年初态、全国统计桥接、来源用途及净碳边界，识别可以明确迁入的增量。
- 对照供需、设备替代和审批分配机制，检查气电零调度、光伏施工限制与煤/CO₂ 代理退步，避免只扩大参数网格。
- 在统一窗口、信息、统计范围与参数用途下复跑候选，再讨论阶段合并或完整 Q2 验收。保持 Draft，不以本次交流取代另外两人的最终评审。
