# R2-B2：可靠创建与审批

## 实施前方案

基线为 PR #14 的 Merge Commit `07153198a3f25b2da2acb5eed2db06dfa7e26c84`，
审核 HEAD `60d6e839a58a13d8957bfd04561fdb93fdedbe62`。分支
`codex/r2-b2-reliable-creation`。原用户未跟踪文件保留；不合并本阶段 PR。

现有问题不是缺少目录：M4 把可复用的校验、尝试、对账和重试预算写在 Graph 闭包内，
类型却限定 SQLite；Assistant 内部再通过 LangChain Tool 使用确定性创建。审批节点的
interrupt 与业务执行实际是不同责任。现有嵌套子图同时承担真实恢复身份，不能直接删除。

本阶段采用如下边界，不重构修改/完成、意图选择或 HTTP 会话生命周期：

- `application/ports/tasks.py` 增加已绑定 scope 的最小 TaskCreator（create_task/lookup），
  不提前增加 change_task；移动能力异常的唯一实现，原异常导入保持同一对象。
- `application/use_cases/task_creation.py` 提取可靠执行的共享步骤及无 Graph 的运行入口。
  使用原 dict 结果和原分类，保留 SQLite OperationalError 的历史分类作为显式兼容债务，
  不引入 SQL、连接或事务。HTTP BusinessUnavailable 继续向外传播，不伪造未执行。
- `application/agent/workflows/reliable_task.py` 保留原 State、节点/边/路由与 fault_plan，
  节点复用共享步骤；`approval_session.py` 负责 interrupt 与批准后的原嵌套驱动。
- `application/agent/tools/reliable_task.py` 保留模型可见契约和可信 operation_id 构造边界。
  Assistant 内部取消 Tool 中转，直接调用原可靠子图，再调用共享事实核验。
  默认模型不获得新的写工具；普通业务创建入口由可信调用方负责授权。
- 旧 workflows/tools 路径显式重导出单一实现；Bootstrap/demo 导入新归属。
  不创建 Repository/UoW、泛化执行器类或未来的 Port。

兼容验证：先完成未修改代码的全量基线；保留原 B0/B0.1/B1 Gate 与快照，增加共享步骤
与独立业务入口的真实 SQLite/HTTP 对照、异常/审批/别名/依赖验证。固定旧源码生成历史
父子 Checkpoint，由候选恢复，再新进程验证；核实 namespace/config、operation_id、Task ID、
版本和一次业务效果。仅调用次数可重放，不能把请求一次当作副作用一次。

任何旧子状态无法恢复、未批准写入、未知结果被吞、Prompt/API/SSE 变化都停止该修改。
执行全量 pytest、完整旧源码矩阵、B1 读取恢复、离线 10 场景、真实 HTTP 重启、R1 兼容、
pip check/compileall/定向 Ruff/diff check；实际结果随后追加，计划不算通过证据。

## 验收结果

下表 python 均为 `.venv-py312/Scripts/python.exe`，Python 3.12.8。报告写入忽略目录
`reports/r2-b2/`；公开去敏摘要见 [R2_B2_ACCEPTANCE.json](R2_B2_ACCEPTANCE.json)。

| 实际命令/检查 | 结果 |
|---|---|
| 改动前 `python -m pytest -q` | 206 passed，527.92s；0 failed/errors/warnings |
| M4/M5、B0 故障、Assistant、R1 架构定向 pytest | 80 passed，108.75s |
| `python -m pytest -q tests/test_r2_b2_creation.py` | 32 passed，68.39s；首轮失败另保留于下文 |
| `python -m pytest -q` | **238 passed，531.47s；0 failed/errors/warnings** |
| `python -m scripts.verify_r2_baseline --contracts-only --out reports/r2-b2/contracts.json` | PASS，固定原快照未刷新，完整契约精确一致 |
| `python -m scripts.verify_r2_baseline --out reports/r2-b2/compatibility-first.json` | PASS，5 组矩阵/17 workers；全量 pytest 再次运行，完整结果隔离复制为 compatibility.json |
| `python -m scripts.verify_r2_b2_creation --out reports/r2-b2/intermediate-standalone.json` | PASS，4 路径/12 workers；尝试数、完整执行身份、单操作/单任务/版本 1、第三进程终态不写 |
| `python -m scripts.verify_r2_b1_reads --out reports/r2-b2/nested-read-compatibility.json` | PASS，读取恢复 4 路径/12 workers |
| `python -m productivity_agent.evaluation --out reports/r2-b2/offline-evaluation.json` | 10/10；真实模型调用 0 次 |
| `python -m scripts.verify_final_delivery --out reports/r2-b2/local-delivery.json` | PASS，真实认证 HTTP、三进程重启，明确不是 Docker |
| `python -m scripts.verify_r1_compatibility --baseline 40d837c19f42ffd373686c30f4797df2e2598e23 --out reports/r2-b2/r1-compatibility.json` | PASS，双 App 完整 OpenAPI/路由、静态页、JSON/SSE、旧库和草稿恢复 |
| `python -m productivity_agent --demo` | 退出码 0，M1 真实 Graph 返回 conflict/备选 |
| `python -m pip check` | No broken requirements found |
| `python -m compileall -q src tests scripts` | 退出码 0 |
| 定向 Ruff（所有本轮 Python 变更） / `git diff --check` / `git diff --cached --check` | 全部通过；未格式化无关文件 |

全量 pytest 的原 B0 Gate 与独立 B2 Gate 的 candidate_source 均与最终 src manifest 完全相同；
公开摘要记录其哈希。原 tests、B0/B0.1 验证器和固定夹具未修改或放宽。CI 保留原步骤和
artifact，另上传 `r2-b2-creation-recovery`，由新增 pytest 实际生成。最终提交 CI 在 PR 中核对。

## 实际职责与设计取舍

| 位置 | 职责与调用者 |
|---|---|
| ports/tasks.TaskCreator | 同步 create_task/lookup；SQLite、已绑定 OwnedTaskStore、HTTPTaskStore 结构满足；不暴露身份选择 |
| ports/tasks.AmbiguousCommitError、TransientWriteError | 能力失败的唯一类型；持久化模块和旧 services 路径重导出相同对象，原 catch/继承关系保持 |
| use_cases/task_creation.validate_creation | 原请求校验、1..5 重试上限和错误 patch；连 bool 属于 int 的旧细节也保留 |
| attempt_creation / reconcile_creation / retry_creation | 原异常集合、状态 patch、对账与预算；不吞 HTTP RuntimeError，不将 None 扩大解释为任意远端永久未提交 |
| create_task_reliably | 可信调用者提供严格 bool 审批后，无 Graph 执行共享步骤；False 不写，非 bool 拒绝；无新模型 Tool 注册 |
| create_task_once | Business HTTP 的原单次授权写边界；不引入重试、不改变 Adapter 回执或异常 |
| verify_created_task | 以相同请求 lookup，对比实际 Task ID；不能核验返回 None，读取故障继续抛出；Assistant 保留原 needs_review/中文回复 |
| agent/workflows/reliable_task | 原 validate/attempt_create/reconcile/retry_gate 驱动与 State；节点只调共享步骤；fault_plan 为兼容测试接缝 |
| agent/workflows/approval_session | 原审批 payload、严格布尔 resume、节点/路由；批准后保留原位置嵌套可靠子图 |
| agent/tools/reliable_task | 单 operation 的可信 Tool 适配；名称/参数/描述/mock_only/返回不变，不内建新授权体系 |
| 原 workflows/approval_session、reliable_task 与 tools/reliable_task | 显式别名，同一实现，无转发类或算法副本 |

不把整个可靠 Graph 当成普通用例引擎：那会保留非 Agent 能力对 LangGraph 的依赖。
也不把持久路径改成普通 while 循环：那会失去已有子 Checkpoint。两种驱动复用一份步骤，
只有运行控制不同。中间状态 patch 保持旧 dict，不另造业务实体或镜像 GraphRuntime Port。

保留 SQLite OperationalError 的直接识别是有意识的权衡：它属于已冻结的旧失败契约，
策略没有 SQL/连接/事务。若此轮改成新通用异常，会改变外部可捕获类型、对账边界或重试，
不能冒充等价迁移。当前先消除具体 SQLiteTaskStore 类型和旧 services 依赖，不隐藏这项债务。
HTTPTaskStore 的 409 和对账读取失败差异继续原样表征；未改协议、Schema、事务或指纹。

## 恢复验证与独立调用证据

原 B0 完整矩阵使用固定 `40d837c19f42ffd373686c30f4797df2e2598e23` 生成历史数据，
覆盖 Assistant/Draft、legacy/auth、SQLite/HTTP、同步 M5 审批与 Chat Memory。实际 B2 候选
已通过；另检查所有有匹配重放的创建调用，完整 checkpoint_ns 相等，不仅首段相等。

新增 `scripts.verify_r2_b2_creation` 补充四条固定旧来源路径，每条三个新解释器：

| 路径 | producer 断点 | 候选实际结果 |
|---|---|---|
| M5 Approval → Reliable | 已提交且尝试数 1，进入 reconcile 后中断 | 只恢复 lookup；recovered、尝试数仍 1、原 Task ID/版本 1 |
| M5 Approval → Reliable | 提交前失败一次，在第二次尝试写入前中断 | 只恢复第二次 create；created、尝试数 2、单 Task/操作记录 |
| 可信 Tool → Reliable（外层 execute 图） | 已提交，在 reconcile 中断 | 同一完整 namespace/config，原任务与一次业务效果 |
| 可信 Tool → Reliable（外层 execute 图） | 第二次尝试写入前中断 | 原子 namespace 保留、尝试数 2，第三进程终态不再调用 Store |

实测继承父 SqliteSaver、thread_id、recursion_limit=27。恢复前完整父/子快照相等，恢复后
子 namespace 集合保持；消费时完整调用身份与旧断点一致。审批路径在 interrupt 后、批准前
业务任务数为零。每例最终 task_operations=1、任务版本=1，结果任务与真实业务读取一致。
这是合成节点中断，不等同于硬断电。B0 继续覆盖 Web 的 AsyncSqliteSaver、认证和远程服务。

新增 16 个策略样本以固定旧代码运行真实 SQLite 为 oracle，比较候选 Graph 和非 Agent
入口的完整结果、异常类型/文本、调用序列和任务内容。覆盖提交前后、预算耗尽、原始
ConnectionError/OperationalError、未知读取、原始 TimeoutError、不合法参数及幂等冲突。
另验证真实 HTTP 写前/写后超时、5xx、对账失败、跨 owner 相同 operation_id 隔离，和
阻止所有 Agent/Graph/Tool/HTTP 框架导入时真实 SQLite 创建及重放。没有用假存储替代集成。

## 中间失败记录

- 权限审核最初按旧 B1 禁止合并规则拒绝；收到用户直接确认后重新核查 HEAD/CI，再执行
  Merge Commit。原 main 从 da613ce 前进到 0715319，未改写历史。
- 首次相关 pytest 命令误写不存在的 test_task05_assistant.py：未运行测试、退出码 4；
  原日志保留，改用实际 test_task04_assistant.py 后 80 passed。
- 新测试首次 31 passed / 1 failed：新增工具要求三个进程 PID 不重复，Windows 将旧 producer
  的 34092 分配给后续 verifier。已核实源路径/调用记录，改为 PID+入口时间证明新进程实例；
  完整 namespace/计数/持久化断言未放宽。随后 32 passed；独立强化子状态 Gate 也通过。
- 定向 Ruff 初次发现迁移后的导入顺序和新测试局部规则问题，修正后通过；无大面积格式化。

## 后续边界

本阶段没有实施修改/完成用例、Assistant 规划/Prompt、Graph State 全面拆分、HTTP Sessions
迁移或 Memory/RAG。旧 facade 继续支持公开导入，B3–B6 尚未授权。真实模型调用 0 次，
预估/实际模型费用均 0 元；Docker、真实模型能力、硬断电及任意私人历史库未执行。
