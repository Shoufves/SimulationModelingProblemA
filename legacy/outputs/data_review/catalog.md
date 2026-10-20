# 观测数据目录

生成时间：2026-10-18T00:15:41+08:00

共17个文件、471个数值单元；其中112个在注明范围内通过证据检查。

数值单元计数，跨文件可能重复，不是独立样本数。准入限登记用途，不代表全国模型数据齐备。

候选和已核验文件保留在同一观测目录，通过正式清单与本表识别，避免移动文件破坏路径及哈希。正式清单为workflow/model_inputs.json，核验依据为data/evidence_reviews.json。

|文件|年份|数值单元|来源|准入状态|
|---|---|---:|---|---|
|[anchors_2025.json](../../data/observations/anchors_2025.json)|2025|20|S02, S04|候选，未准入|
|[coal_balance_2015_2023.json](../../data/observations/coal_balance_2015_2023.json)|2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023|87|S10, S11, S12|候选，未准入|
|[demand_energy_total_2015_2024.json](../../data/observations/demand_energy_total_2015_2024.json)|2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024|10|S01|限定用途已核验|
|[demand_real_gdp_growth_2015_2024.json](../../data/observations/demand_real_gdp_growth_2015_2024.json)|2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024|10|S06|限定用途已核验|
|[electricity_demand_official_2024.json](../../data/observations/electricity_demand_official_2024.json)|2024|11|S24|限定用途已核验|
|[energy_consumption_2015_2024.json](../../data/observations/energy_consumption_2015_2024.json)|2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024|50|S01|候选，未准入|
|[energy_official_communique_2024.json](../../data/observations/energy_official_communique_2024.json)|2024|33|S13|限定用途已核验|
|[fuel_production_2023_2024.json](../../data/observations/fuel_production_2023_2024.json)|2023, 2024|6|S16|候选，未准入|
|[gas_apparent_consumption_2024.json](../../data/observations/gas_apparent_consumption_2024.json)|2024|2|S23|限定用途已核验|
|[gas_official_report_2024.json](../../data/observations/gas_official_report_2024.json)|2024|20|S22|限定用途已核验|
|[macro_growth_2015_2024.json](../../data/observations/macro_growth_2015_2024.json)|2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024|30|S06|候选，未准入|
|[petroleum_balance_selected_years.json](../../data/observations/petroleum_balance_selected_years.json)|2015, 2020, 2021, 2022, 2023|45|S14, S15|候选，未准入|
|[power_capacity_2015_2024.json](../../data/observations/power_capacity_2015_2024.json)|2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024|70|S05|候选，未准入|
|[power_generation_2015_2024.json](../../data/observations/power_generation_2015_2024.json)|2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024|51|S07, S08, S09, S13|候选，未准入|
|[power_official_release_2024.json](../../data/observations/power_official_release_2024.json)|2024|10|S17|限定用途已核验|
|[qinshan_asset_permit_case.json](../../data/observations/qinshan_asset_permit_case.json)|2021|1|S26, S27, S28|限定用途已核验|
|[renewable_operation_official_2024.json](../../data/observations/renewable_operation_official_2024.json)|2024|15|S25|限定用途已核验|

## 已核验子集的使用限制

- demand_energy_total_2015_2024.json：仅同版发布序列的总能源条件回算及四种统计基线；不批准原整表结构，不作部门燃烧、全国ABM、CO2或跨版因果结论。原图/截图未本地归档，证据为明示人工文字摘录。；审查R-S01-DEMAND-20261017，证据data/raw/official/S01_demand_excerpt_20261017.txt。
- demand_real_gdp_growth_2015_2024.json：仅近似实际GDP链接指数与已实现GDP条件回算；原宏观整表不准入，不能当不变价GDP绝对额或盲测。原图/截图未本地归档，证据为明示人工文字摘录。；审查R-S06-GDP-20261017，证据data/raw/official/S06_gdp_excerpt_20261017.txt。
- electricity_demand_official_2024.json：仅2024年度四类用电规模与结构锚点、同比参考；无历史行为校准或逐时负荷；规模以上工业发电量不能当作全国总发电量求供需缺口。；审查R-S24-20261017，证据data/raw/official/S24_page_capture.txt。
- energy_official_communique_2024.json：仅独立2024公报横截面与口径分析；尚未完成洗选损耗及GDP历史修订桥接，不用于十年连续校准或全国预测。；审查R-S13-20261017，证据data/raw/official/S13_selected_capture.txt。
- gas_apparent_consumption_2024.json：仅2024快报表观消费独立横截面和与报告消费的口径诊断；不替换消费总量或与S22部门份额混算，不用于未桥接历史校准。；审查R-S23-20261017，证据data/raw/official/S23_page_capture.txt。
- gas_official_report_2024.json：官方发布行业报告的2024国内横截面、天然气用途/进口结构及核算接口；不采用国际商业数据及2025预测，不与快报表观消费相乘推部门绝对量，不用于未桥接历史校准。；审查R-S22-20261017，证据data/raw/official/S22_selected_capture.txt。
- power_official_release_2024.json：仅独立2024发布版本横截面；与年鉴存在差异，禁止未桥接拼接历史校准。；审查R-S17-20261016，证据data/raw/official/S17_page_capture.txt。
- qinshan_asset_permit_case.json：仅秦山7台机组许可文件回放与附件3条厂级记录身份映射；不核实精确装机/实际退役/发电或全国初始化；生成日为回放信息时点约定；审查R-QINSHAN-ASSETS-20261017，证据data/raw/official/S26_qinshan_permits_2017_capture.txt、data/raw/official/S27_qinshan_extension_2021_capture.txt、data/raw/official/S28_qinshan_design_life_capture.txt。
- renewable_operation_official_2024.json：仅2024技术参考、利用率及版本范围诊断；抽蓄能量未知、生物质排放未知，禁止混版计算容量因子、完整全国初态或未经桥接的历史校准。；审查R-S25-20261017，证据data/raw/official/S25_selected_capture.txt。

题给附件标准表另见data/processed/attachment_assets.json及outputs/attachments/report.md；不计入上述官方观测单元，不能当全国总体。

更新目录：运行scripts/build_data_catalog.py或run_verified.ps1。
