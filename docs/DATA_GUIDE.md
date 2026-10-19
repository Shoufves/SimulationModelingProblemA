# 数据入口、去重及使用边界

2026-10-20 V10补充：Q2专项准入共26份来源、511条观测；新增两份调度方法原件只提供方法动机。条件非电残差和初始在建队列属于研究推断，八技术发电及装机目标共享上游数据，不能计作新增独立观测。详见[V10结构修复](solutions/p2-lb-review10-structure.md)。

先查 `data/catalog/datasets_unified.csv`，再看对应来源与final限制。`data/catalog/sources_unified.json` 保留原登记记录、原ID、命名空间、原件哈希、摘录证据和迁移后的路径。`source_key` 区分yx、mmj和lb各批资料，不能仅凭S01等局部编号关联。

## 三层数据与去重

1. **原件层**：按SHA256判断字节完全一致的文件；仅保留一个实体。`path_aliases.json` 将每个旧路径映射到保留位置，`archive/organization_20261017/file_disposition.csv` 记录理由。网页摘录与原始网页、不同发布版本即使数字相同也不合并。
2. **来源转录层**：保留不同作者的原转录表和原始JSON，因为它们包含各自定位、用途审查或可复现输入契约。它们是证据材料，不能同时追加成独立样本。保留表格不表示在模型中重复计算。
3. **唯一记录视图**：`data/processed/unified/nbs_history.csv` 对已明确同版同口径的统计局生产/消费/装机，以及表9-8的GDP增速子集去重。键为版本、指标族、年份、地域、变量和单位；原值不换算、不补零。相同键的数值冲突进入 `nbs_record_conflicts.csv`，不进入唯一记录表。统计局表3-4的GDP增速保留单独指标族，与表9-8不静默合并。

`nbs_record_provenance.csv` 保留每个候选单元的原表、行列、来源状态和是否被选用。已准入的mmj需求总量/GDP子集优先，但仅继承“条件需求回算”的原用途；其余先取yx同版转录，lb补早年。相同来源的多次转录不构成独立验证。

本轮该视图汇集704个候选数值单元，得到362条唯一记录，移除342个重复单元，未发现同键数值冲突。覆盖2005—2024的范围不等于所有技术/部门均有完整20年数据。未选择进入这张视图的其他数据仍分表保留，不能将本次局部语义去重夸大为全库统计口径已统一。

## 推荐入口

| 用途 | 位置 | 状态与约束 |
|---|---|---|
| 官方附件 | 根目录附件1—4；data/processed/attachment_assets.json | 原件必留；890条记录保留重复组及不确定字段 |
| 全国同版历史 | data/processed/unified/nbs_history.csv | 去重视图；不自动批准全国ABM用途 |
| 真实需求与资产案例 | data/observations/；workflow/model_inputs.json | 九个限定子集，由原evidence_reviews检查 |
| 全国与地区补充 | data/processed/下yx表；data/processed/lb/base/ | 单位、统计期和来源边界见目录；不同上游不直接拼接 |
| 进口来源 | data/processed/lb/trade_alternatives/；ai_trade/ | 管道气/LNG/煤/油分年分单位；小计和调整不作来源国 |
| 通道与外部条件 | data/processed/lb/international/ | 同一货物可经多通道；半年、季度、估计和预测分开 |
| AI用电 | data/processed/lb/ai_trade/compute_electricity_anchors.csv | 总算力参照，不是AI专属观测；未来值是预测 |
| 居民群体 | data/processed/lb/household/ | 主用已发表群体汇总；旧未加权汇总仅诊断 |
| 煤炭就业 | data/processed/lb/employment/ | 九省区+全国存量；不得重复求和或解释为净失业 |
| 技术政策原件 | data/raw/lb/base/reports、policies及其他主题 | 已存待提取仍是有效资产，不以“未结构化”为由删除 |

## 必须隔离的内容

- `commodity_price_references.csv` 是混合用途表，逐行查看status；候选世界银行新版及lb年度/月度价格继续隔离。月年吻合不解决来源版本疑点。
- `transmission_lines_candidate.csv` 保留类型和年份待核状态，不能直接用于2024实际输电网络。
- 2018小时负荷是重建序列，只能按其身份做形状和接口检验；不改称2024逐小时实测。
- EI标准热值气体与国内报告、2024与2025 LNG、EJ与万吨，不无据换算相加。马六甲两表差异继续保留。
- `data/restricted/household/` 仅为原始保留，不逐行读取、不进入默认目录或重建命令；本轮只做文件级哈希和迁移。社会分析优先公开群体汇总。
- 原下载失败日志和伪装为zip的HTML响应只是诊断证据；目录存在不等于成功取得数据。来源状态必须随使用披露。

## 原流程如何重建

yx的6个程序已集中到 `scripts/`，原数据路径保留，离线整理与审计可直接运行。lb的代码集中到 `tools/legacy_lb/`；其原相对路径由 `scripts/reproduce_lb.py` 在临时目录恢复，完成后比较表值并清理。此入口只支持已审查的离线配方，拒绝网络，且不会覆盖统一原件。原采集脚本仍保留供后续按需维护，本轮未重新下载资料。

历史来源目录保存原路径是为了保留证据字节。实际寻址请通过统一目录或path_aliases，不手改原sources/evidence_reviews以伪造哈希准入。新增输入需另建实质审查，不以迁移后的存在检查代替来源核验。

## Q2本分支新增用途

`data/catalog/q2_national_input_review.json`记录24项原件/参考表的限定用途、页表、哈希、冲突和排除项；`data/processed/q2/national_observations.csv`为511条原图复核/原始API或CSV匹配的观测。新增的统计类别、折标和2016/2024收购政策依据仅增加定义及限定用途，没有把政策网页的2025数量加入历史训练。它们仅支持本分支全国聚合条件研究，不代替共同输入批准。价格、设备年龄、在建队列及未来路径的观察/假设区别见 `workflow/q2_national_design.json`。

新增核对发现：NBS表9-2原图2006年能源总量为286467万吨标准煤，统一CSV原为284647；Q2采用原图并登记冲突，原Q1输入及输出未回写。WDI2024汇率与国家统计公报不一致，Q2采用公报7.1217而不取平均。NBS一次电力及其他与非化石的类别对应已有官方段落支持；数量采用只在2015—2021拟合的复合统计桥，仍不等于完整实物平衡或实测发电煤耗。桥独立回测、常数对照及范围说明见 `statistical_scope_review.json` 和[修复报告](solutions/p2-lb-review9-response.md)。BTR的CO2分项与GCB年度诊断分存，不能直接相加。
