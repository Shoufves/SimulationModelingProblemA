# PR13第二次复审修复证据

本目录追加原冻结协议下的77条完整重跑路径，不覆盖父目录R0—R9历史。两项P2、执行范围与复现入口见[修复响应](../../../docs/research/n2-pr13-review2-response.md)。

| 文件/目录 | 内容 |
|---|---|
| primary | 8条件×5规则，40条新路径；原门槛全部通过 |
| controls | 8条件×4规则，32条新强对照 |
| fixed | 4条新固定项目消融，保留投资/守恒及风险边界 |
| reproduction | 新W08独立进程、PYTHONHASHSEED=83；9091数字字段，exact_match=true |
| final_acceptance.json | 最新机器验收；内部条件N2候选通过，人工pending，N3不支持，硬服务界0/8通过 |
| feedstock_counterexample.json | 真实LP只改煤电容量：原料总缺供相同、气原料恶化100个百分点，修复口径检出 |
| roundoff_counterexample.json | 对实际旧归档明确注入一ULP/1元差异的正反测试，不冒充独立仿真 |
| previous_revision_comparison.json | 40条新旧共有科学字段exact_match；新原料服务/预测向量显式排除 |
| independent_accounting.json | 从年度路径独立重算40条累计折现成本 |
| material_observed_scope.json | 4320个煤/油/气年度服务单元，身份完整且实际缺供为0 |
| research_tests.json、legacy_test_reuse.json | 本次22项研究测试通过；339项既有测试按相关文件未改动复用，未重新执行 |
| verifier_sources | 本次核验源码快照；执行入口仍在仓库scripts |
| archive_manifest.json | 306份打包证据的存储/解压哈希；之后添加的图、导航和QA另记delivery_manifest |
| figures、qa | 当前科学图与交付审计 |

读取大JSON用标准库gzip无损解压。归档还原或比较器重跑不等于仿真重新执行。四ULP容差只适用于累计折现成本，其余数值、决策、结构和守恒规则仍用固定PR14比较器；不把数值近似通过改称位级一致。
