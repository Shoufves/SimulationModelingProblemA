# 问题二 PR14 与已合并主干的整合

基线为已合并 PR13 的 main `dba50210dcf0636e9b54e4137077ae710070eb2e`；来源为 lb PR14 `1b8f465783afe7505c8d4e65ec43ada18c311daf`。2026-10-20 通过 Git fetch 与 GitHub API 核对，PR14 为 open / Draft，尚未合并。用户明确选择将其问题二方案接入本工作区；这不等于代替其他成员批准，也不改写上游未过的科学门槛。

## 当前入口与采用范围

```powershell
python -B -X utf8 run.py q2
python -B -X utf8 run.py q2 --config workflow/q2_pr14_integration.json
# 单案检查，仍实际求解到2060并与PR14参考逐项比对
python -B -X utf8 scripts/run_q2_pr14.py --only S0 --output-dir outputs/q2_pr14/s0_check
python -B -X utf8 scripts/check_q2_pr14_integration.py
python -B -X utf8 scripts/check_q2_pr14_portability.py
python -B -X utf8 scripts/check_q2_pr14_integration.py --verify-results
```

默认入口重算 S0 和23个敏感性/初态条件，采用PR14已提供的提取输入快照。不是读取参考路径充当计算；参考只在求解结束后比对。不会重新选择历史参数，也不宣称本次重读了全套原始PDF。

`outputs/q2_pr14/integrated/latest.json` 指向最近尝试；其 `integration.json` 记录入口、源代码、输入、结果哈希、完整24案状态及实际失败信息。任何后续失败都会令 latest 变为失败，旧成功仍在 attempts 中留档。读取结果前可调用 `scripts/run_q2_pr14.py` 的 `verify_latest()`。新入口只允许写入 `outputs/q2_pr14/` 或 `tmp/q2_integration/` 的子目录，拒绝覆盖 Q1/Q3、旧Q2和N2研究成果。

旧配置 `workflow/q2_inputs.json` 和 `workflow/q2_national_design.json` 仍显式选择历史 PR9 路线，以保留既有审查命令的含义；它们不是PR14配置。新版用户使用默认 `run.py q2` 或上方新配置。旧科研入口 `scripts/run_q2_national.py` 原字节保留，供问题3继续使用。

| 采用的材料 | 位置及用途 |
| --- | --- |
| PR14原模型及导入依赖 | `vendor/q2_pr14/`；独立进程加载，不覆盖原 `src/energy_model` |
| 提取输入、设计、24个参考路径 | `data/processed/q2_delivery/`；保持上游原字节和原manifest |
| 新版答题稿、表图、视频、AI披露 | `outputs/question2_delivery_20261020/`；上游交付快照，非本轮重新撰写/渲染 |
| 历史参数、评估摘要、来源索引 | `outputs/q2_revenue_recalibration/`、`outputs/q2_current_delivery/20261020T004752442611Z/`；历史证据，未伪装为本次训练 |
| 逐文件采用登记 | `data/catalog/q2_pr14_integration_review.json`；原commit、路径、Git blob、SHA256和角色 |
| 本轮新复算与验证 | `outputs/q2_pr14/`、`outputs/q2_pr14_review/`；独立于历史收据 |

新增的是执行接线、隔离与验证，不引入新模型、参数、政策或结论。PR14的财政实付/欠款、新旧机组费用、共同销量下的项目私人收益、2024重建初态等机制原样采用。本次没有把PR14未交付的26个其他案例加入问题三。

## 为什么保留版本边界

问题三的准入明确锁定旧Q2源码、历史参数与输入。直接合并PR14同名模型会让准入失效，并改变原H01/H02、政策比较和解释。当前 `run.py q3`、问题三所有代码/配置/产物均保持原字节；只在统一启动器的Q2分支增加新版路由。非Q2路由以AST比较核对。

N2增量的底座本来就是同一个 PR14 SHA；`src/transition_research/`、研究协议及已发布证据原字节保留。少延退4.51%—13.37%、逐服务风险不增的内部N2条件结论及8/8硬服务界未过的限制不变。本次没有把N2额外策略自动加进PR14的S0，也没有将Q2和旧Q3的S0数值视为同一模型下可直接相减的结果。

## 验收目标与科学边界

验收目标为：默认Q2确实执行PR14；24案2025—2060逐年字段、目标与峰值通过上游严格结构/数值比对；既有测试、新入口失败语义和Q3路径回归通过；Q1/Q3/N2原科学材料不变；来源、参考、结果篡改均拒绝；原件与原用途准入不变。实际检查及数量看 `outputs/q2_pr14_review/`，不将历史日志当作本轮运行。

### assumptions / approximations

沿用PR14的单区域代表日、2024规模观测与年龄/债务/现金/队列重建、2018电价与厂用电延续代理、条件技术和外生经济路径；N2沿用其独立外生公共额度限制。细节见上游答题稿及各案 `assumptions`。本次为已核验提取输入的复算，完整原件再解析、历史重训和视频/论文重建未执行。

### 已证实结果

来源模型与输入按固定SHA保持不变；本轮24案完整复算记录与保护回归见验收目录。上游答题稿中的2030/2060数值应从本轮 S0 路径再核对后使用，历史误差来自原2015—2021训练、2022—2024已接触评估，不是新盲测。

### exploratory results

敏感性、财政权限和初态扰动仍为冻结假设内的条件探索；参数变化同时影响投资、缺供和成本，不单独赋予全国因果含义。N2仍为内部条件N2候选，未增加全球原创/N3主张。

### 被证伪的假设及原因

“新版所有历史精度均优于旧版”不成立：PR14总装机MAPE24.90%（原门槛20%），光伏装机26.77%（原门槛25%）未过，光伏发电误差也较旧版升高。“可以覆盖同名Q2模块而不影响Q3”不成立：Q3继承源码哈希锁与直接模型依赖明确要求保留其版本。

### 当前 unresolved questions

历史容量偏差、容量补偿与后续差价政策完整接入、财务初态代理、氢/CCUS内生投资、季节/区域/全年可靠性仍未解决；这些是上游明确边界。是否以后把整个Q3迁移到PR14并重做H01/H02和政策对照属于另一个研究任务。本次不关闭这些问题，不声称系统保供或全国碳中和获得认证。

## 原件流程与历史文件定位

本次约11MB源材料采用包保留必要源代码、提取输入与答题证据，没有重复提交PR14全套大型原件和逐时账本。`QUESTION2_DELIVERY_20261020.md`、`QUESTION2_PR_HANDOFF_20261020.md`、原 answer_manifest 与 source_snapshot 保持上游字节，里面的原路径指向PR14完整目录，不能据此误称它们在当前轻量整合目录中全部存在。

需要重跑原件解析或历史训练时，使用固定SHA的完整 Git 导出目录（例如在 `tmp/q2_integration/pr14_full/` 解开 `git archive 1b8f465783afe7505c8d4e65ec43ada18c311daf`），再执行上游 `scripts/run_q2_current_delivery.py --only S0 --workers 1`。不要直接在 `vendor/q2_pr14/` 执行原件入口或自行改写上游哈希。若本地缺该Git对象，应从 origin 获取该固定提交后导出；默认新版Q2复算不依赖此Git对象、网络或本机旧tmp目录。

本轮AI参与代码接线、文档说明及自动化验证；不新增“主要代码全人工编写”或“已人工签认”的声明。上游作者、历史AI披露与人工审查状态保留。
