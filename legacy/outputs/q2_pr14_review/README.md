# PR14与main整合的本轮证据

总验收为 `acceptance.json`。可按顺序重新运行 `run.py q2`、`scripts/check_q2_pr14_integration.py`、`scripts/check_q2_pr14_portability.py`、`scripts/check_q2_pr14_integration.py --verify-results`；最后一步核验当前输入、全部输出哈希、三问保护和独立目录证据后汇总。

本轮基础检查：`checks.json`；主干347项测试见 `tests.json` / `tests.log`，N2研究22项见 `n2_research_tests.json`，PR14原入口8项见 `upstream_runner_tests.log`。这些均为本轮实际运行，不是复用PR13测试数量。

Q2：`../q2_pr14/integrated/latest.json` 指向本轮24案2025—2060重算，逐案比较使用PR14原容差并保留实际浮点差异。`clean_delivery.json` / `.log` 是无Git目录、初始无tmp的独立交付目录，换哈希种子后的S0和GDP高增长复算；不是声称在干净目录再次重算了全部24案。

Q3：`q3_path_regression.json` 显示S0/SP/ST各36年、8,424个数值字段与已合并产物完全一致；未重跑全部160点H01、H02/政策批次。Q1未重算，由 `preservation.json` 对所有旧科学代码、输入、结果的原字节保护提供证据。N2未重跑77条研究路径；其源码、协议和科学证据未改，22项研究测试重新执行。

`preservation.json` 对main起点2,755份非受限旧文件检查Git blob，一致；仅列明的Q2路由、导航、目录登记允许改动。受限数据不读取内容，只检查存在/大小。

`sandbox_failure/` 保留第一次Windows沙箱临时目录WinError 5导致的失败。之后在普通本地权限下运行同一套命令，通过；未降低断言或数值容差。`workspace_audit.json` / `formal_inputs.log` / `key_scan.log` 为本轮资料、用途准入与密钥检查。旧 `outputs/validation` 与 `outputs/workflow` 收据在检查后恢复原字节。

工程检查通过不等于装机误差达标、全国保供成立或团队正式批准。本轮仅接线/复算/保护已有科学成果，AI使用及上游局限见整合说明。
