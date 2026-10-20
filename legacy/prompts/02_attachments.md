> 统一工作区执行约束：先读 `只读工作区/final.md` 与 `docs/IMPLEMENTATION_ROADMAP.md`。本文为原mmj阶段提示，仅复用核验流程；历史基年/窗口、情景编号及研究优先级以final为准（2024候选初态，2015—2021训练、2022—2024已接触留出；S0/SP/SG/ST后接SW/SGW；H01/H02优先）。gemini创新仅在基础验收后启用，缺失输入不得填零。

# W1 题给附件清洗与用途落实

执行总控提示词。输入为原始四个xlsx、workflow/provided_inputs.json及docs/04_attachment_audit.md。原始文件保持不变。

生成可重复执行的附件读取与清洗程序，以及逐行溯源的标准记录，建议置于data/processed/。保留source_file、sheet、row、original_name、original_capacity、original_unit、location、province、coordinates、year、operating_status、verification_status、processing_reason。未知字段为null。

重点处理：
- 火电633条具名记录、同名及容量字段关系，区分“推测MW”与已确认单位；不得默认全部为煤电。
- 水电与抽蓄分开，核查同名、额外列及尾部空白；抽蓄功率不能推出能量容量。
- 风电16条和核电17条是有限清单；坐标、地区、年份需核查。
这些数量来自初步审计，本阶段重新读取复核；不为匹配旧数量而修改数据。

输出outputs/attachments/report.md及附件用途表：每份附件用于哪个指标、哪个主体/案例、什么区域表达，哪些记录不能使用以及原因。至少展示可核实记录如何进入区域资产描述或代表性案例；不具代表性时只支持案例，不能伪造全国权重。

验收：原文件SHA256不变，原行可追溯，重复判定有证据，单位和缺失状态明确，四附件均有实际用途或可解释的限定。
