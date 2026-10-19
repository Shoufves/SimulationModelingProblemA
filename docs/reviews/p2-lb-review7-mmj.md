# PR #9 · mmj 本地独立评审

评审日期：2026-10-19（Asia/Shanghai）。评审人：mmj。候选：PR #9，`p2/lb`。

**建议：需修改。** 本报告针对 `dd3cff550d63fa137bcf6082ea3e94d0ce0d5115`，共同 base 为 `804ec15ee43874303986a7ad91b2cde05c65b124`。不构成 GitHub Approve、Request changes 或另外一人的批准。没有修改候选代码、发布评论或合并。

本次遵循 README、AGENTS、final、实施路线、运行与数据指南、`docs/17_git_collaboration.md`，并重新读取 Issue #7。Issue 已确认共同 base，PR #8 与开发并行；不沿用上一轮“须等待 #8 合并”的旧状态。不使用子智能体。

**1. [P2] 发电投资审批没有执行已经计算的施工上限。**

定位：`src/energy_model/q2_national.py:141–145`；审批端 `:259` 仅再限资金和共同预算。

`limit` 按独立施工能力与 GDP 算出并导出为 `construction_limit_mw`，但申请量继续乘 `investment_response` 和风光比例，没有最终 `min(..., limit)`。当前最优参数的 `investment_response=1.75`，因此这不是只在非法参数下发生的情况。用提交中的默认参数实际运行 2025—2060，出现 **28 次最终获批量超过该上限**。例如 2031 年水电获批 **35,050.56 MW**，上限 **20,028.89 MW**，为 **1.75 倍**；2032 年煤电获批 **89,185.45 MW**，上限 **50,963.11 MW**。

资金有余不等于施工能力有余。这会影响装机、建设支出及后续供需路径，违背本轮安装/建设能力约束。应明确硬施工容量与行为响应的区别，并在最终批准时执行施工容量限制；重新校准与运行受影响结果。增加“充足资金、正 NPV、投资响应大于 1 时最终审批不越施工容量”的反例。若作者本意是将 `limit` 定义为响应前的参考规模，则需正式重新定义并记录实际硬上限，而不能继续用“施工上限”证明已受限。

同一组参数下，仅在内存对照中给申请量补上此上限，2030 风光装机由 5.7448 TW 变为 5.1495 TW，2060 正 CO₂ 由 7.4933 Gt 变为 8.3414 Gt。这说明问题会影响科学结果，不能只改日志字段后沿用原结论。该对照未重新校准，只用于定位影响，不作为修复后的研究结果。

证据：`independent_probes.json` 的 `construction_limit_exceedances`、`construction_cap_impact.json`；可重跑 `D:/CSF2026/mmj/mmj_pr9_probes.py` 与 `D:/CSF2026/mmj/mmj_pr9_cap_impact.py`。

**2. [P2] 输入在启动阶段缺失时，旧成功状态未失效，并阻断修复后的重试。**

定位：`scripts/run_q2_national.py:401–408`，相关归档发生在 `:391–398`。

执行器先移动旧结果、建立空输出目录，再在 `try` 外计算 `CODE`/`INPUTS` 哈希；直到这些都完成才写 `running`。在隔离夹具中放入前次成功记录，删除 `data/processed/q2/national_observations.csv` 后运行实际 `main()`：返回 `FileNotFoundError`，但 `latest-attempt.json` 仍是 `status=success_conditional_candidate`、`output_valid_for_this_attempt=true`。空目录没有 `run_manifest.json`。恢复输入后再次执行，又得到 `Refusing to replace unowned output`。

`verify_latest()` 因清单缺失会拒绝读取，因此不声称该函数把新运行错误认成成功；问题是公开“最新尝试”状态错误，而且正常恢复输入无法继续复跑。现有故障注入在 `preflight()` 内抛错，跳过了更早的哈希失败点。

应在任何可能失败的输入读取前撤销前次成功有效性，将指纹计算纳入失败落盘流程，保留可辨识的本次输出目录归属；验证首次运行、已有成功后缺文件、恢复文件后正常重试三种情形。

证据：`independent_probes.json` 的 `missing_input_startup`；夹具保留在 `startup_missing_input/`。候选输入未被修改。

**3. [P2] 全国入口只核对来源哈希，没有执行逐来源用途和待审状态约束。**

定位：`scripts/run_q2_national.py:54–67`。

`preflight()` 仅检查审查文件顶层身份、产品哈希和来源哈希/路径。它不检查每条来源的 `status`、`allowed_use`，也不将观测行的实际用途与来源准入绑定。独立反例保留原件、产品和全部哈希，将 19 条来源状态改为 `pending_review`，用途改为 `candidate_inventory_only_NOT_national_initialization_or_calibration`；真实 `preflight()` 仍接受 **511 条观测**并生成训练误差尺度。

这是对被撤回/尚待核验用途的误接纳，不能由“文件字节未变”替代用途审查。应校验必需来源集合、逐来源状态、允许用途与实际初始化/校准/诊断用途对应关系，拒绝缺少、待审或不覆盖当前任务的授权；为“哈希不变但用途撤回”增加反例。本次反例通过内存替换审查对象调用实际函数，未改正式文件，详见脚本。

当前默认提交也有具体用途不一致：`data/catalog/q2_national_input_review.json:79` 将 GCB 标为 `external_boundary_diagnostic_only`，观测表记录为 `external_diagnostic`，但 `scripts/run_q2_national.py:171–177` 实际将它缩放后用于峰年/峰值判断。方案文档已公开桥接方法，所以不认为这是隐瞒；需要对该新用途明确审查、登记，并让程序核对用途，而不是仅保留诊断授权。

证据：`admission_probe.json`；`D:/CSF2026/mmj/mmj_pr9_admission_probe.py`。

**已实际完成的检查**

| 检查 | 结果与证据 |
|---|---|
| 精确提交及文件 | Git HTTPS 不通，改用 GitHub 只读 API 获取缺失对象，逐个核对 Git OID；重建精确提交和树，独立 detached worktree；`fetch_evidence.json` |
| 运行环境 | 独立 venv，Python 3.12.14；锁定 numpy 2.3.5、SciPy 1.16.3、Mesa 3.3.1、pandas 3.0.1、matplotlib 3.10.7 安装成功；复用已有 Q1/数据依赖 |
| 全量测试 | 248 项，失败 0、错误 0、跳过 0；`tests.json`、`tests.log` |
| 工作区审计 | 通过；`workspace_audit.json`、`audit.log` |
| 密钥扫描 | 通过；`key_scan.log` |
| 原九子集准入 | 通过；`formal_inputs_status.json`、`original_nine.log` |
| Q1 独立复跑 | 18 个科学产物与提交结果逐字节一致；`independent_checks.json` |
| 原件与原契约 | 官方 PDF、附件 1—4、只读目录三原件、三份准入契约，共 11 文件与 base 字节一致 |
| 导出账本复核 | 2025—2060 共 36 年：一次能源、燃烧与净 CO₂、现金、融资和消费者预算逐项通过；跨年 SOC 衔接通过；`independent_checks.json` |
| 数据原件抽查 | NBS 9-2、9-15 图像；BTR 物理 30—31 页的 CO₂ 列、单位、碳汇符号及备忘项；IEA 物理 60—61 页核电燃料与 O&M 独立列。未发现这些抽查值的转录错误 |
| diff 范围 | 263 文件；没有新增 ≥50 MiB 文件；原受保护文件无变化 |
| 自设反例 | 上述三项问题实际复现；另外检查的“设备付款前后零申请转正”在默认路径未复现，未列为缺陷 |

完整 Q2 入口已独立执行完成：**2250 组训练全部成功，77 组条件试验全部成功，26 份科学产物与作者提交逐字节一致**；更换 `PYTHONHASHSEED=7919`，真实耗时 1924.1 秒。独立审计为 14 项通过。证据见 `reproduction_comparison.json`、`q2.log`，完整新运行保存在 `q2_run/`；Q1 保存在 `q1_run/`。未运行作者固定输出路径的两份完整验收脚本，因此不把作者“30项验收”宣称为本次执行数量；本次使用独立目录复跑和独立断言。

**共同验收与科学边界**

工程测试通过并不能覆盖上述反例。B2 的施工上限、B3 的用途约束、B7 的失败语义尚有待修项。Q1 回归与原件保护 B8 已有独立证据。

本版诚实披露了已接触评估、同口径排放留出缺失、全国单节点代表日、初态/金融重建和净移除外推，未把这些限制隐瞒为盲测或官方预测；不要求它必须得到“达标”结果。Issue #7 对完整 Q2 的 B4/B5 验收及共同配置确认仍须单独核定。尤其非化石占比代理、CO₂ 条件桥接、代表日结果不能自动升级为正式口径全国全指标验收，三人尚未确认的标准也不由本评审代签。

另有一项共同验收交接待办：实际执行 Issue #7 的 `run.py q2 --config workflow/q2_inputs.json --output-dir outputs/q2/review_pr9_common_entry` 仍得到 `blocked_national_inputs`；本版完整模型走默认 `run.py q2` / `workflow/q2_national_design.json`。作者文档已披露两者不同，不能据此说作者隐藏了失败；但合并前应统一契约/入口，或在 Issue #7 记录并确认替代命令与配置。不能将默认入口的成功当作原共同命令已经通过。

上述问题修复并提交新 SHA 后，至少复跑相关反例、基础回归及完整 Q2 入口；影响投资逻辑时须重新训练并更新全部科学产物。mmj、yx 应分别针对同一最终 SHA 复审，取得两人的明确批准后才由团队决定合并。本次没有代为发布任何远端评审。

结束前再次查询 PR：head 仍为上述完整 SHA，PR open、未合并。主工作区 `main`、个人 `p1/mmj` 与评审 worktree 的 Git 状态均为空；本次产物已移至本报告所在目录。旧备份、stash、其他评审目录与分支均保留。没有读取 `data/restricted` 内容。
