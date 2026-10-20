# 附件标准表字段与处理方法

读取入口：scripts/build_attachments.py。依赖Python 3.10+及openpyxl（仅用于读取，不修改原工作簿）。运行run_attachments.ps1。原始四附件的SHA256在读取前后分别检查。

标准表：data/processed/attachment_assets.json。每条记录对应原始具名行，record_id由附件、技术工作表和原始行号组成。标准表不是全国电站数据库，也不自动成为正式模型输入。

|字段|含义与规则|
|---|---|
|record_id / source_file / sheet / row|稳定原行标识；不按名称合并项目|
|original_name / name|原名称及仅去首尾空格后的名称|
|technology|按题给工作表分类；thermal不等于coal|
|original_capacity / original_unit|原始容量数值；installedcapacity未明确单位，original_unit为空|
|declared_kw_header / kw_formula / kw_cached_value / kw_recomputed|保留火电KW标题、原公式和缓存；只解析原表精确的B行×1000公式，不执行任意Excel表达式|
|capacity_mw_from_declared_kw|由明确KW列重算值除1000；仅反映附件单位关系，不确认真实项目容量/年份|
|capacity_interpretation|单位解释的依据；不能因一个项目核实而推广整表|
|location / original_province|原地点文字、原省份列|
|province / province_basis|仅规范显式省份前缀，或按官方逐字段核验修正；不由县名猜省份|
|original_coordinates|原经纬度，始终保留|
|coordinates / coordinate_status|数值范围通过的暂存值仍未验证项目位置；冲突记录设为空并保留隔离原因|
|coordinate_reference_system|坐标系未提供，保持为空|
|year / operating_status|附件未给明确统计年/状态，保持为空|
|official_capacity_reference|带官方日期与核准/建成状态的项目容量参照，不能当作当前在运容量|
|duplicate_group|同名组编号；区分同字段与字段冲突，均不自动删行|
|review_source_ids / verification_status|逐字段复核来源及有限状态，不表示整条记录全面核验|
|issues / processing_reason|缺失、冲突、处理原因等机器可读标记与说明|
|national_calibration_eligible|本轮均为false；需核实时间、范围、单位、重复及代表性后另行评估|
|raw_cells|每个非空原单元格的坐标、原值/公式及缓存值，可回溯|

outputs/attachments/sample_profiles.json按五张工作表统计原记录数、名称数和省份标签。其省份标签尚未全量外部核验，只用于描述题给样本，不作为全国地理结论。

excluded_cells.json保留原表附加内容：火电空格与点号，水电D2合计公式。546个无名称行不生成项目记录，行号在source_sheets中保留。原表任何非空额外内容均可定位，空白不转成0。

attachment_reviews.json记录实质核查过的字段、官方证据文件哈希和限制。记录中核准容量与建成容量都保留各自参考日期，不反推附件统计年份。本轮仅4个项目有部分字段核验，绝不将890条记录全部标为已核实。
