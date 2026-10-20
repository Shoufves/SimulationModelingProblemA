# Q1/Q3补充研究审查证据

本目录对应起点 `7d52f439992503eac5978c6f218f5289fe3e2195` 之后的创新和文本审查。原Q1/Q2/Q3源码、数据准入和正式产物保留；不覆盖 `outputs/q3_review/acceptance.json` 的历史身份。

| 文件 | 用途 |
|---|---|
| `q1_q3/q1_source_exposure.json` | 同工作簿跨运输方式来源合并、未知桶保守界和原件单元格复核 |
| `q1_q3/q3_effectiveness.json` | 实际部署等价类、年度/事件账核验、Shapley归因、去重H01比较 |
| `q1_q3/text_metrics.json` | 四篇目标的指标分子分母、重复句、局部重合位置；不预测AI作者比例 |
| `q1_q3/evidence_checks.json` | 24组文稿关键数值的实际字段、换算与短句核对 |
| `q1_q3/unchanged_baseline.json` | 原科学资产与起点Git对象及当前SHA256核验 |
| `q1_q3/run_manifest.json` | 代码、目标、文稿、文献、数值登记与输出指纹；Python和哈希种子 |
| `verification/acceptance.json` | 本轮技术验收与人工pending状态，文稿身份和复现指纹 |
| `verification/gates.json` | 实际全量测试、基础审计、正式输入及密钥扫描的命令/日志/代码指纹 |
| `verification/reproduction_manifest.json` | 第二目录实际运行的完整manifest，保留不同哈希种子及结果指纹 |
| `verification/tests_sandbox_failure.log` | 首次沙箱ACL失败证据；由随后本地权限的通过结果取代，不隐藏失败尝试 |

运行命令见[复现指南](../../docs/RUNNING.md)。`q1_q3_reproduction/`是第二次独立目录，指标逐字节比较后仅保留复现收据，不重复提交同内容。探索目录用于设计诊断，已被正式结果取代并由Git忽略。两次补充分析复用同一套已验收科学账本，不等于再次运行整个全国模型。

本轮自检经过范围冻结、先例与诊断核对、证据绑定和独立复现四个阶段。核验中纠正了引用链接/书目并剔除了重复的H01物理条件；没有根据结果改原参数或扩大事件域。创新等级与文本指标的边界见[创新复核](../../docs/research/q1-q3-innovation-review.md)、[文本审查](../../docs/research/q1-q3-text-review.md)。正式外部AI率和全网重复率未测，人工表未签，不作比赛最终验收承诺。
