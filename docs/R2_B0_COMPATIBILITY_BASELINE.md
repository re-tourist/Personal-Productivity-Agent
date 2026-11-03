# PPA R2-B0：Application 迁移前的兼容基线

固定来源：`40d837c19f42ffd373686c30f4797df2e2598e23`，R1/R1.1 Merge Commit。
工作分支：`codex/r2-application-architecture`。本阶段只新增测试、夹具、验证工具和设计记录，
`src/`、Graph、Prompt、业务数据库 Schema、公共接口没有修改。没有进入 B1–B6。

## 1. 审核决定与设计约束

D1–D6 的正式批准和兼容条件追加在 [R2-A 第 14 节](R2_A_APPLICATION_DESIGN_AUDIT.md#14-r2-b0-审核决策记录追加保留上述-r2-a-原始记录)。
四层设计不变：Domain 只有三个获批的旧兼容例外；Agent Sessions 不依赖 FastAPI；
模型默认无真实写 Tool；SQLite/HTTP 差异保留；文件按职责适度拆分，不增加未使用抽象。

特别调整 D2 的实施前提：可靠策略可以提取，但不能把当前嵌套 Graph 当作无持久状态的函数删除。
旧 Graph 驱动、节点和调用顺序是历史恢复契约的一部分。先让旧节点复用无框架步骤，
再用真正迁移后的代码验证旧 Checkpoint；若无法保持身份，停止该切片，提交兼容设计，不能擅自迁移数据。

## 2. 可复现来源与夹具

| 交付物 | 作用 |
|---|---|
| `tests/fixtures/r2_b0/contracts.json` | 固定旧源码产生的两个 App 完整 OpenAPI、有序 routes/operationId、JSON/SSE 响应；七张 Graph 的节点/边/State 字段类型、required/optional、channel/reducer、输入输出 Schema、interrupt 配置；Prompt 多行原文、两类 LLM Schema、Tool 参数/描述/输出、现有 Store/Extractor 方法签名 |
| `tests/fixtures/r2_b0/constraints.txt` | 记录现有 Python 3.12 环境依赖版本；仅 constraints，不新增依赖、不升级框架；CI 安装应用时使用 |
| `tests/fixtures/r2_b0/observed-summary.json` | 本轮实际验收摘要，移除绝对运行路径和原始数据库内容；历史证据，不作为未来候选源码的期望值 |
| `scripts/r2_baseline_worker.py` | 同一测试驱动分别导入历史源码与候选源码，执行真实 Graph、Saver、业务 Store 和 HTTP App |
| `scripts/verify_r2_baseline.py` | `git archive` 固定 SHA 的源码，独立 producer → consumer → verifier 进程；记录实际 import 根、PID、版本、源码哈希、Checkpoint/业务数据库审计 |
| `tests/test_r2_b0_compatibility.py` | 全量 pytest 必跑上述矩阵；限制 Domain 兼容例外范围 |
| `tests/test_r2_b0_ports.py` | 真实 SQLite/独立 HTTP 服务的异常、回执、未知结果、过滤与归属表征 |

所有数据库、生成凭证、原始日志放入新的 `.pytest_cache/` 子目录，不提交 SQLite 二进制。
固定合成日期为 `2026-11-03` 的 reference_now，任务到期 `2026-11-04T15:00:00+08:00`。
独立 HTTP Business 服务只绑定 loopback、单 Worker。未访问用户数据或外部服务。

确定性处理仅包括：以出现关系映射随机 UUID、静态 HTML 以 LF 规范化后计算哈希、
State 注解中去掉 ASLR 函数内存地址。HTTP OpenAPI 全量对象精确相等，数组/路由/SSE 事件顺序不排序。
SSE 原文换行、JSON escaping、headers、错误 detail 和终态仍比较。Graph edges 按端点规范排序，
节点列表与字段信息保留；SQL 原始数据不做 UUID 替换，恢复时核对原始 ID。
不将动态时长、PID 或绝对运行路径当作公共协议。

Python：3.12.8。主要观察版本：LangGraph 1.2.19、checkpoint 4.3.1、sqlite checkpointer 3.1.3、
langchain-core 1.7.3、FastAPI 0.162.0、Pydantic 2.14.2、HTTPX 0.28.1；其余版本见夹具与 constraints。
CI 完整获取 Git 历史，避免浅克隆找不到固定来源；测试不允许回退到 HEAD 生成旧数据。

初次冻结命令（仅 B0 建档时执行，不可用来覆盖未来回归）：

```powershell
.venv-py312/Scripts/python.exe -m scripts.verify_r2_baseline --refresh-snapshot --contracts-only --out reports/r2-b0/contracts.json
```

后续 Gate 必须不带 `--refresh-snapshot`。即使带此选项，也只能从固定旧源码冻结，
并先验证候选契约精确一致，不能从候选实现生成“期望值”。

## 3. Checkpoint 兼容矩阵与边界

| 历史来源/存储 | 模式 | 生成状态 | 新进程恢复与核对 |
|---|---|---|---|
| Web Assistant / AsyncSqliteSaver / `m6-checkpoints.sqlite` | legacy/auth × SQLite/HTTP | ready、澄清、待审批、拒绝终态、批准终态、从待审批在新进程拒绝、执行前静态中断、创建/修改/完成提交后丢失 | 原 snapshot/interrupt 等值、批准/拒绝、继续澄清、`/recover`、重复决定、owner、operation_id、Task ID、版本和业务次数 |
| Web Draft / 同一 AsyncSqliteSaver 文件 | legacy/auth × SQLite/HTTP | 待审批、拒绝/批准终态、新进程拒绝、执行前中断、提交后丢失 | 原 snapshot/interrupt 等值、审批、新进程持久恢复、重复决定 409；执行中断用现有 Graph API 恢复，因为 Draft 无 recover HTTP 路由 |
| M5 同步 Approval / SqliteSaver / `m5-checkpoints.sqlite` | 原有 CLI legacy 模式 | 待审批、拒绝/批准终态、新进程拒绝、执行前中断、提交后丢失 | 同步 Command/None 恢复；保留原节点、布尔 resume、op、任务及一次创建 |
| M5 Chat Memory / SqliteSaver / `m5-chat-checkpoints.sqlite` | 原有 CLI legacy 模式 | 一轮终态、第二轮停在 echo 前 | None 恢复原消息、AI/Human 类型反序列化、同 ID 替换语义、第三进程终态读取 |

Web 每个模式 16 个会话：10 Assistant + 6 Draft；四个模式共 64 个会话。
M5 Approval 另 6 个线程，Chat Memory 另一个线程。
每个模式均固定旧源码生成 → 候选源码恢复 → 候选源码第三进程验证。
M5 原 CLI 不存在 HTTP 认证模式；不声称验证了不存在的认证 CLI。

提交后丢失的可复现方式：测试包装真实 Store，**先完成真实写入**，再抛出仅测试使用的
BaseException，使生产 `except Exception` 不能把它转换成终态。Graph 保存失败/待执行状态，
关闭旧进程后从原 SQLite 文件恢复。另用 runtime `interrupt_before` 固定 execute/echo 边界。
这模拟“业务已提交而 Graph 未记录成功”，不声称等价于 OS kill、电源故障或 SQLite 磁盘损坏。

每个 Web 模式恢复后应有 12 条任务、12 条创建索引、2 条修改索引，版本总和 14。
第三进程重读/重放后的完整业务审计须相等；旧已创建 Task ID 为恢复后 Task ID 的子集。
修改/完成保持原 Task ID，版本从 1 到 2；子图重放使用原 operation_id。
M5 Approval 为 4 条任务；拒绝不创建。Chat 的消息 ID reducer 必须替换已有同 ID 的 HumanMessage。

**证据范围**：B0 禁止修改业务实现，当前 producer/candidate 的 `src` 哈希相同。
因此这是实际旧源码文件 → 当前源码文件、不同 OS 进程与真实 SQLite 数据的兼容基线，
尚不能证明未来搬迁后的代码已兼容。必须在 B1–B6 每次真实迁移后重跑同一生成器，禁止把
候选实现复制到 baseline。外部已存在的任意用户 Checkpoint、其他依赖版本和损坏数据库未验证。

## 4. 嵌套 ReliableTaskGraph 的运行时结果

实际 instrument 在真实 `create_task/change_task` 执行位置调用 LangGraph `get_config()`，
仅记录安全字段；然后调用原实现，不替换事务/幂等。另直接读取真实 Saver 的子 Checkpoint。

| 调用链 | 观察 |
|---|---|
| Assistant.execute → 可信 LangChain Tool → Reliable Graph | 继承 Assistant thread_id、AsyncSqliteSaver、recursion_limit=20；写入执行点 namespace 为 `execute:<parent-task-id>\|attempt_create:<child-task-id>` |
| Draft.execute → Reliable Graph | 同样继承 AsyncSqliteSaver 和原 thread key；原 HTTP Draft 未显式提供 recursion_limit，测试直接调用时为 20；不把默认值统一掉 |
| M5 Approval.execute → Reliable Graph | 继承 SqliteSaver，探针自定义 recursion_limit=23 原样传递；不是独立无配置调用 |

真实数据库存在 `execute:<parent-task-id>` 子 namespace，保存 ReliableTaskState，
包括丢失后的 ready/attempts=0 中间状态；本次 BaseException 注入下读取到的
`pending_channels` 为空，不声称已保存异常对象。不是仅上下文中出现了一个 saver 对象。
重启恢复的提交后丢失场景再次进入同一父 execute namespace；旧 op 在 producer 和 consumer
各一次 Store 调用，第三次终态验证零写调用；事务索引和任务版本不重复。

因此 **网络/Store 调用可能重放，业务副作用不得重复**。删除 Tool 中转时必须考虑同一
嵌套调用位置/子图调用序号和 namespace 的身份，不能仅保持顶层节点名和字段名。
新的无框架策略只能在保持恢复兼容的旧驱动内逐步复用；扁平化或删除子 namespace 不是已验证的改动。
通用库文档提供背景：[LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)，
最终结论以本项目固定版本的实际子 Saver 数据和恢复断言为准。

## 5. Adapter 故障与 Port 语义

| 触发条件 | SQLite | HTTP / 应用可观察结果 |
|---|---|---|
| 创建 op 重用且参数不同；修改 op 重用且 payload 不同 | IdempotencyConflict | Business HTTP 409 / `conflict_read_again`，Adapter 对两类均抛 VersionConflict |
| 修改 expected_version 过期 | VersionConflict | 同样为 HTTP 409 / VersionConflict；不能从 409 判定一定只是版本过期 |
| 创建重放 / lookup / 创建回执 | 返回当前 Task | 相同；任务后来已修改/完成时返回新的当前状态，不是最初创建快照 |
| 修改重放 / 修改回执 | 返回存下的历史 result_json；重放先于版本检查 | 相同；历史回执不能替代当前 task 核验 |
| 创建请求 5xx（包括已提交后 5xx） | 无对应 HTTP 类别 | AmbiguousCommitError；不得断言未执行 |
| 修改请求 5xx | 无对应 HTTP 类别 | BusinessUnavailable(RuntimeError)；Assistant 转对账路径 |
| 创建/修改写后或写前传输超时 | 本地测试接缝区分 transient / ambiguous | 均 AmbiguousCommitError；必须通过回执/当前任务验证是否提交 |
| 对账读 5xx 或读超时 | SQLite 连接/操作异常按既有代码分类 | BusinessUnavailable，不是 None；只有一次成功读取的 operation=null 才表示未找到 |
| 提交后超时 + 对账读失败 | 不统一 Adapter 异常族 | M4 抛 BusinessUnavailable；Assistant 返回 needs_review/result=null；Draft 500，Checkpoint 留在 execute 待恢复、status 仍 approved，重复 decision 409；真实业务记录已存在 |
| Calendar 跨午夜事件 | 展示按 start_at 日期过滤 | 该日展示可能为空，但冲突计算仍输入全量事件；不能为了复用查询能力缩小冲突范围 |
| 同一 kind/thread 重复 claim | SQLite IntegrityError，无覆盖 | 同 owner 和不同 owner 都抛出，原归属保留；不能重构成无条件幂等 upsert |

表中未知提交的现有行为不是新的完备性承诺。B0 只固定异常传播；未修复 Draft 的 500 和
M4 对 HTTP 读异常族的处理。后续 Port 必须允许这些现有异常，不能把它们规范化为“未执行”。
若要改善返回协议或重试策略，另开行为变更审核，不能藏在目录迁移中。

身份与授权沿用原有测试：账户配置/Token Hash、常量时比较、请求级 owner-bound store、
身份预检、legacy 隔离、跨用户 404；B0 恢复矩阵另验证无认证 401、另一 owner 的会话/任务 404、列表为空。
未改变 bearer 处理，也没有提交临时 Token。

## 6. 验证命令与工程结果

以下 `python` 均指现有 `.venv-py312/Scripts/python.exe`，环境关闭在线模型和 tracing。
网络测试使用本机隔离合成 HTTP 服务。首轮工具失败保留于忽略的 `reports/r2-b0/`，
包括测试注入越过 AnyIO 边界、回调启用顺序和类型 repr 内存地址；均只修正新增工具，没有修改业务实现。

| 命令 | 结果 |
|---|---|
| 改动前 `python -m pytest -q` | 158 passed，260.07s，0 failed/errors/warnings |
| `python -m pytest -q tests/test_r2_b0_ports.py` | 19 passed，120.50s，0 failed/errors/warnings |
| `python -m scripts.verify_r2_baseline --refresh-snapshot --contracts-only --out reports/r2-b0/contracts.json` | 固定来源全量契约与候选精确相等；不是从候选生成期望 |
| `python -m pytest -q` | **179 passed**，602.69s，0 failed / 0 errors / 0 warnings；其中含 17 个独立 worker 的全量固定旧来源恢复矩阵 |
| `python -m pytest -q tests/test_r2_b0_ports.py tests/test_task06_operations.py` | 最后补强测试服务“所有写请求”日志后 **27 passed**，203.88s，0 failed/errors/warnings；复验原业务集成与新增故障断言 |
| `python -m productivity_agent.evaluation --out reports/r2-b0/offline-evaluation.json` | 首轮 5/10；5 个任务用例均为沙箱临时目录 PermissionError / WinError 5，原报告保留 |
| 同上，`--out reports/r2-b0/offline-evaluation-retry.json`（授权的沙箱外执行） | **10/10**；0 真实模型、0 费用；未修改评测或业务代码 |
| `python -m scripts.verify_final_delivery --out reports/r2-b0/local-delivery.json` | PASS；真实认证 HTTP/三进程重启/Task ID/版本/归属/重复审批 |
| `python -m scripts.verify_r1_compatibility --baseline 40d837c19f42ffd373686c30f4797df2e2598e23 --out reports/r2-b0/r1-compatibility.json` | PASS；两个完整 OpenAPI/有序路由/页面/旧 Draft 数据恢复 |
| `python -m pip check` | No broken requirements found |
| `python -m compileall -q src tests scripts` | 退出码 0 |
| `python -m ruff check scripts/r2_baseline_worker.py scripts/verify_r2_baseline.py tests/test_r2_b0_ports.py tests/test_r2_b0_compatibility.py tests/helpers/business_server.py` | All checks passed |
| `git diff --check` / `git diff 40d837c -- src` | 前者无空白错误，后者应为空 |

`pytest-compatibility.json` 是全量测试中实际生成的详细矩阵报告，由 CI 上传 artifact。
单独复现完整生成/恢复 Gate：

```powershell
.venv-py312/Scripts/python.exe -m scripts.verify_r2_baseline --out reports/r2-b0/compatibility.json
```

**未执行**：真实 Qwen、付费服务、Docker、生产多 Worker、OS 硬断电/kill 故障、任意用户历史库恢复。
真实模型 0 次；预估/实际模型费用均 0 元。未将脚本式模型替身称为真实模型能力验收。

## 7. 后续 Gate 与停止条件

- B1 只读/日程迁移：精确 OpenAPI/SSE/Tool/Prompt/State 快照 + 跨午夜冲突范围 + 完整历史恢复矩阵。
- B2 可靠创建：保留父/子执行身份、旧节点驱动和 fault_plan；固定旧来源的中断/写后丢失恢复，
  op/Task ID 不变、子 Checkpoint 可读取、一次业务效果。遇到旧子 namespace 无法消费，停止。
- B3 修改/完成：保留历史回执/当前事实区别、HTTP 409 差异、一次版本增长、未知提交的异常传播。
- B4 LLM/Planning：Prompt/Schema/Tool 原文快照，保守选择、引文、澄清、新值、授权边界不变。
- B5 Sessions：不依赖 FastAPI；保留 Assistant 与 Draft 不同的重放、HTTP 500/待恢复及 shared lock 语义。
- B6 收束：三个 Domain 例外不得扩张；新主实现不反向依赖兼容 facade；无循环、无空 Port；
  两 App/旧启动入口和全部原验证保留。Memory/RAG 只创建获批职责说明。

每阶段都跑全量 pytest、10 场景离线、真实 HTTP 重启、固定旧来源兼容生成器、pip/compile/Ruff/diff。
未知结果被吞掉、未批准写入、op/Task ID/版本/归属变化、旧 Checkpoint 不能消费、
Protocol/Prompt/SSE 变化均为停止条件。依赖升级另立基线，不通过刷新 fixture 掩盖回归。
本阶段完成后停止并等待审核，不自动进入 B1。
