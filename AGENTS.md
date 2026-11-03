# Codex working agreement — Personal Productivity Agent

这是项目根目录的长期协作约束，适用于 Codex 对本仓库的后续任务。若与用户在当前任务中的明确要求冲突，以用户新要求为准。

## Project intent

- 单仓库的 LangGraph + Qwen（百炼） + FastAPI + SQLite 的**本地 Agent 工程作品集**，不是生产级多租户服务。
- 核心链路包括日程规则、结构化意图、只读模拟 Tool Agent、人工审批、幂等任务写入、恢复与 SSE。
- 首先阅读 `docs/PROJECT_HANDOFF.md` 和 `docs/architecture.md`；验收使用 `docs/ACCEPTANCE_MATRIX.md`，最新 R1 证据与 R2 交接见 `docs/R1_ARCHITECTURE_REFACTOR.md`；Task 01/02 是历史任务。
- 用户和 ChatGPT 负责业务与架构裁决，Codex 负责具体工程实现及可复核测试。

## Engineering constraints

1. **以本地工作树为准**。修改前查看 `git status`、相关模块及现有测试；不要覆盖用户未提交改动。
2. **先测试和根因，再修改**。不要为了让测试变绿而删除/跳过/弱化断言，或用 Fake 取代应当验证的真实集成链路。
3. **业务事实与图状态分离**。业务 SQLite 保存任务与幂等记录；Checkpointer 保存图状态；`thread_id` 不等于 `operation_id`。
4. **副作用保护**。未获批准不得创建任务；同一操作重试应复用稳定幂等键；不能把 timeout 当成写入失败。不得让未经授权的 LLM 自主执行实际外部写入。
5. **默认不使用付费模型**。未经用户单独授权，不调用真实千问百炼、不得启用付费 API；不自动切换到更昂贵的模型。
6. **保护敏感信息**。不得输出/提交 Key、`.env`、令牌、连接凭证、私人数据；日志/报告须去敏。
7. **不要擅自扩大范围**。真实第三方服务、生产认证、PostgreSQL、gRPC Server、复杂 Multi-Agent 不在当前修复范围，除非明确获批。
8. **Git 安全**。未经用户明确要求，不 push、不 merge、不打 Release、不重写 Git 历史、不删除分支；大型重构前先提交方案与影响评估。
9. **不猜测成功**。测试/演示必须标明实际执行、未执行及限制；框架导入成功 ≠ 完整业务验收通过。

## Preferred workflow

- R1 后的主实现：`interfaces/` 负责 HTTP/CLI，`domain/` 负责纯业务契约与规则，`infrastructure/` 负责存储/SDK/身份/追踪，`bootstrap.py` 负责资源装配和生命周期。新实现禁止反向依赖旧 `api/`、`services/`、`providers/`、顶层 `cli.py` 兼容模块；不要复制实现。
- R2 才迁移 `workflows/`、`tools/`、CalendarState、ScheduleIntent、AgentIntent 及设计 Use Cases/Ports。R1 未创建未使用的 Application/Memory/RAG 抽象；后续任务须明确授权后再改这些内部逻辑。
- 保留两个独立 FastAPI App 与全部旧启动入口；身份/bearer 只能绑定当前请求资源，不能放到共享 Store/Graph。业务库、归属库和 Checkpointer 分离；保持单 Worker 与进程内锁约束。
- 架构改动验收增加 `tests/test_r1_architecture.py`（包含延迟导入/循环依赖/请求绑定），全量 pytest、离线评测、`python -m scripts.verify_final_delivery --out <隔离报告路径>` 和 `python -m scripts.verify_r1_compatibility --out <隔离报告路径>`；不能把模型装配检查描述成真实 Qwen 验收。定向 Ruff 仅覆盖新增/改动文件和已有约定范围。

- Task 01：先记录原始测试基线，再开展技术审计与受控工程整理（2026-11-02 用户追加授权）。允许有证据、行为兼容的小范围整理；大范围业务逻辑或架构调整只提交方案。原只读任务保存在 `docs/history/TASK_01_READONLY_ORIGINAL.md`。
- Task 02：工程基线与关键集成验收；允许小范围修复和补测试，不升级主要依赖、不改业务语义，不执行 Git Commit/Push/Merge/Release。工程入口见 `docs/ENGINEERING_BASELINE.md`，结果见 `docs/audits/TASK_02_2026-11-02.md`。
- 后续：每轮只修一组共同根因 → 局部测试 → 全量回归 → 离线评测 → 清晰的 git diff。
- 保留可复现的命令和失败 traceback；区分单元测试、真实 LangGraph 集成、HTTP、跨进程恢复和在线 Qwen。
- 在执行具有副作用/费用的动作前先征得用户明确授权。

## Required reporting format

每轮回答必须包括：

1. 本轮范围与结论（成功 / 部分完成 / 被阻断）；
2. 证据：命令、日志摘要、文件与行号；
3. 修改文件和原因（只读阶段填“无”）；
4. 测试结果：passed / failed / errors / warnings，并说明未运行项；
5. 风险、下一步建议、Git 工作区状态；
6. 真实模型调用次数与预估/实际费用（默认 0 次）。
