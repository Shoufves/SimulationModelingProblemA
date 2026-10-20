# PR14 固定模型依赖

来源是 lb 的 PR14 提交 `1b8f465783afe7505c8d4e65ec43ada18c311daf`。此处保留便携复算需要的源代码及其本地导入闭包，原字节不改；这是固定版本的模型依赖，不是另建成员工作区。

统一入口为仓库根目录的 `python -B -X utf8 run.py q2`。不要在此目录直接运行上游脚本：运行器会先按 `data/catalog/q2_pr14_integration_review.json` 校验代码、输入、参考结果与交付文件，再复制到临时目录，用独立进程执行上游的 `run_q2_portable.py`。数据唯一入口在根目录 `data/processed/q2_delivery/`，临时副本运行后清理。

隔离原因：PR14 的 `q2_national.py` 和 `q2_operations.py` 与问题3已验收的版本不同。直接覆盖会改变问题3的科学结果，原哈希准入也会拒绝。当前旧模型继续支撑问题3；问题2主入口使用此处新版。N2方法仍使用自身协议固定的同一 PR14 SHA，不改动研究方法或既有结果。

`accepted_main_run.py` 单独来自整合前 main `dba50210dcf0636e9b54e4137077ae710070eb2e`，只供非Q2入口的AST回归检查；不属于 PR14 模型或执行入口。其余文件的逐项 Git blob、SHA256、大小与原路径见整合登记。

上游原件解析、历史训练和报告重建脚本作为可追溯源码保留；便携依赖不包含全套原始资料，不能把直接调用这些脚本当成完整原件复核。完整原件流程应在该固定提交的完整目录运行。具体边界见 `docs/solutions/p2-pr14-main-integration.md`。
