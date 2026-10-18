# P1/lb：问题一研究交付

基准为最终整合报告主线；创新备选不提前加入Q1评分。共同base为 `7a65d068d19eea2f7dd8161a618a3ad8d66f98b8`，本人分支 `p1/lb`。本分支为问题一候选，交由PR进行团队评审；不代替另两人批准。

## 阅读结果

- [三个子问题最终核对](p1-lb-final-acceptance.md)：本地研究可收尾；逐项说明覆盖、已补缺口、保留限制和正式评审状态。
- [补齐前复查](p1-lb-recheck.md)：保留初版不足及修正依据。
- [完整研究报告](../../outputs/q1/p1_lb/report.md)：历史、四维、区域、成本、九类能源及配套、静态账和后续接口。
- [用途审查](p1-lb-input-review.md)：已有原件的实际核验、三张新增转录与边界。
- [四轮迭代记录](p1-lb-iterations.md)：问题、修改和实际检查证据。
- [补充用途审查](p1-lb-additional-review.md)：新增价格、地区、成本、氢气和生物质原件的实际核验。
- [输入指纹](../../workflow/q1_inputs.json)：21份处理输入和37个原件来源；不替换原准入契约。

## 方法与题面覆盖

|题面要求|产物|方法/边界|
|---|---|---|
|全国规模、消费生产、装机发电与趋势|history.csv、coverage.csv、report.md|主窗口2015—2024；2005起背景；2005/2014/2015等缺口不插值|
|供给保障|indicators.csv、import_origins.csv|同表净进口/消费；国家来源HHI上下界；无虚构中断概率|
|清洁低碳|indicators.csv、static_balance.json|煤炭份额/绝对标准煤量、实际GDP强度指数、GCB分项；不把天然气算非化石|
|经济性|成本组、价格标准差与coverage|共同2018美元/CF/折现组及技术寿命核算；2024 IRENA单列；价格仅实际相邻年度|
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
```

最低Python3.11；数值处理使用标准库，四张SVG图由ReportLab生成，环境依赖见`requirements-q1.txt`。在安装依赖后，Q1运行不联网。独立复现可指定`outputs/q1/lb_reproduction`，不写其他成员目录。非空且非本实现所有的目录拒绝覆盖。输入失败记录在独立的`*.failed-attempt.json`；此前成功结果保留，但明确不属于失败尝试。

## 当前状态

四轮补齐与核对完成，问题一三个子问题均已形成可复算的本地研究交付，可以收尾。共有2146条来源记录、182条指标记录（110个标识）、31省比较、427条交接记录、36条分能源评价、8组协同方向和4幅图。163项测试、14项审计通过；独立目录18份科学产物逐字节一致，最终检查见[核对记录](../../outputs/q1_review/final/final_verification.json)。

完成判断依据[最终逐项核对](p1-lb-final-acceptance.md)，不以记录或测试数量替代科学覆盖。欧洲气价异常单元格、原油国别和部分生物质细表等缺项保留，禁止超出证据作更细结论；氢消费侧价格为加氢站样本，不能直接用于化工到厂价。A7尚需真实成员评审。PR发布依用户授权进行；正式接受仍需两名成员批准同一最终提交。
