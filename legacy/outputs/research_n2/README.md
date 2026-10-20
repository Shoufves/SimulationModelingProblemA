# N2研究证据导航

最新修复版见[pr13_review2](pr13_review2/README.md)及其[验收](pr13_review2/final_acceptance.json)。本目录原R0—R9及根final_acceptance保留修复前历史身份，不覆盖原641份证据；当前方法采用分原料服务身份与累计成本有界ULP比较。

研究基线为PR14固定提交`1b8f465783afe7505c8d4e65ec43ada18c311daf`，当前分支未合并该PR。研究从`d0c234313509f159f1c449a2372c35686ce9cb15`追加，不改原Q1/Q2/Q3科学结果。

先读[方法、效果与复现命令](../../docs/research/n2-method-and-results.md)、[五类研究记录](../../docs/research/n2-research-ledger.md)，再核对[最终机器验收](final_acceptance.json)。最终结论为项目内部N2经验候选通过；N3不支持、系统硬服务界8/8未过、人工签认pending。

| 目录/文件 | 证据身份 |
|---|---|
| r0、baseline_export.json | PR14完整S0参考复现、代码/输入快照核验；非原PDF重新核验 |
| r1、r2 | 静态配对及完整反馈探索；R1延迟反例保留 |
| r3 | 未锚定版本的失败验证，不被后续成功覆盖 |
| r4 | 针对已接触反例的修订探索 |
| r5、r6、r7、r8 | 历史验证、固定消融、补充强对照与复现；闭环仍可见预设GDP分段信息 |
| r9 | 最终当前信息版本，8条件×5规则；acceptance与extended_comparison为主比较/强对照 |
| r9_fixed | 最终固定项目四规则消融；不计入主条件数 |
| r9_reproduction | 最终W08另进程、PYTHONHASHSEED=83复现，科学字段exact_match=true |
| legacy_tests.json、research_tests.json | 339既有测试与14研究测试，均通过 |
| research_tests_fixture_failure.* | 修复前夹具失败记录，不能代替最终测试 |
| literature-search.json、author-sources.json | 查询收据及作者元数据/摘要；未完成全文穷尽查新 |
| figures | 最终结果的PNG/PDF/SVG科学图，明确收益与计算代价 |
| qa | 交付阶段工作区、正式输入、密钥扫描及归档完整性检查 |

`archive_manifest.json`覆盖打包时641个证据文件，分别记录存储字节和解压字节SHA256。大案例JSON为无损gzip，不是删去路径的摘要；用Python标准库`gzip.decompress`即可读取。后续导航、图与QA文件另由`qa/delivery_manifest.json`记录。科学路径共213条，包含探索、对照、消融和重复运行，不是独立样本数。

`tmp/n2`包含本地执行环境、隔离导出和中间输出，不作为Git交付。归档中的源码快照用于追溯各轮实现，当前复现执行仓库`scripts`入口；只解压并重算验收不等于重新运行仿真。
