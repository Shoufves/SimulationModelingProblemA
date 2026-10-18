# P1/lb：问题一研究交付

基准为最终整合报告主线；创新备选不提前加入Q1评分。共同base为 `7a65d068d19eea2f7dd8161a618a3ad8d66f98b8`，本人分支 `p1/lb`。本分支为问题一候选，交由PR进行团队评审；不代替另两人批准。

## 阅读结果

- [独立评审修订](p1-lb-review-response.md)：C1/C2/L2/L3的修改、原件核对和复审状态。
- [此前本地自查](p1-lb-final-acceptance.md)：保留历史判断，其完成结论已被本轮独立评审撤回。
- [补齐前复查](p1-lb-recheck.md)：保留初版不足及修正依据。
- [完整研究报告](../../outputs/q1/p1_lb/report.md)：历史、四维、区域、成本、九类能源及配套、静态账和后续接口。
- [用途审查](p1-lb-input-review.md)：已有原件的实际核验、三张新增转录与边界。
- [四轮迭代记录](p1-lb-iterations.md)：问题、修改和实际检查证据。
- [补充用途审查](p1-lb-additional-review.md)：新增价格、地区、成本、氢气和生物质原件的实际核验。
- [输入指纹](../../workflow/q1_inputs.json)：22份处理输入和39个原件来源；不替换原准入契约。

## 方法与题面覆盖

|题面要求|产物|方法/边界|
|---|---|---|
|全国规模、消费生产、装机发电与趋势|history.csv、coverage.csv、report.md|主窗口2015—2024；2005起背景；2005/2014/2015等缺口不插值|
|供给保障|indicators.csv、import_origins.csv|同表净进口/消费；国家来源HHI上下界；无虚构中断概率|
|清洁低碳|indicators.csv、static_balance.json|煤炭份额/绝对标准煤量、实际GDP强度指数、GCB分项；不把天然气算非化石|
|经济性|成本组、价格标准差与coverage|共同2018美元/CF/折现组及技术寿命核算；2024 IRENA单列；价格仅同定义区段内相邻年度；混合年度排除，样本不足不报SD|
|协调性与区域|regional_comparison.csv、调节指标|同年31省份额差异；利用率、储能功率与能量分别解释|
|九能源+储能/输送/CCUS|energy_roles.csv、energy_assessment.csv、synergy_assessment.csv|36条四维诊断，8组协同机制、条件、风险及检验方向|
|静态核对与Q2交接|static_balance.json、model_handoff.csv|统计残差保留；初态候选及阻断原因；不称全国已初始化|
|复现与诚实失败|run_manifest.json、新入口和测试|离线、哈希检查、独立目录、失败非零、保护其他成员结果|

保障与协调不合成为安全总分；成本比较只覆盖可比厂端电量服务，不声称解决全系统可靠服务成本。所有研究库均保持上游定义，不能凭汇编数量提高独立证据数。工程门禁与科学覆盖分开验收。

## 复现

```powershell
python -B -X utf8 run.py q1 --output-dir outputs/q1/p1_lb
python -B -X utf8 run.py test
python -B -X utf8 run.py audit
python -B -X utf8 scripts/scan_google_keys.py
python -B -X utf8 scripts/review_q1_delivery.py
```

最低Python3.11；数值处理使用标准库，四张SVG图由ReportLab生成，环境依赖见`requirements-q1.txt`。在安装依赖后，Q1运行不联网。独立复现可指定`outputs/q1/lb_reproduction`，不写其他成员目录。非空且非本实现所有的目录拒绝覆盖。输入失败记录在独立的`*.failed-attempt.json`；此前成功结果保留，但明确不属于失败尝试。

## 当前状态

独立评审要求修改的C1/C2/L2/L3已逐项修订，当前为等待复审的Q1候选，撤回此前“可以收尾”的表述。新增2024年非化石一次消费占比初步测算、新型储能同年规模与地区证据；国际价格按原件定义分段；交付核验改为重新检查实际输入和原件、运行测试并复现。

当前有2170条来源记录、206条指标记录、31省比较、36条分能源评价、8组协同方向和4幅图；记录数量不代表科学验收。最新工程证据见[本轮核验](../../outputs/q1_review/revision1/delivery/final_verification.json)，历史final目录仅保留旧版本证据。

欧洲2024气价异常、原油国别、部分生物质细表、储能SOC/效率/逐时可用率等缺项保留。新增提取和用途仍需团队确认，A7尚待两名真实成员批准同一最终提交。本轮未合并，不提前宣称问题二的全国初始化或预测完成。
