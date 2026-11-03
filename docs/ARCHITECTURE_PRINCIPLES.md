# PPA 架构设计原则

本文件记录 R1.1 前置架构补丁的长期设计意图，不替代具体任务授权或验收证据。
目标是职责清楚、容易定位、依赖可控并能演进，而非减少代码行数或填满目录树。

## 职责模型

| 层/入口 | 职责与边界 |
|---|---|
| Interfaces | HTTP/CLI、请求与响应契约、请求身份边界、SSE；将外部请求转成应用操作，不承载复杂业务规则、事务或 Agent 决策 |
| Application | 协调业务目标；Agent 子系统含 Assistant、Workflow、LLM、Tools 和未来 Memory/RAG；通用用例也允许普通 HTTP 不经过 LLM 调用 |
| Domain | 业务对象、状态、时间冲突、版本约束和规则；独立于 FastAPI、LangGraph、SQLite 和模型 SDK；不是所有数据结构的收容目录 |
| Infrastructure | 数据库、Checkpointer 持久化、HTTP 客户端、模型/离线适配、凭证与运行观测的具体实现；可以依赖业务契约，不主导业务流程 |
| Bootstrap | 在启动时选择、创建、连接实现并管理生命周期；允许知道具体实现，不承担业务决策 |

这是简化的 Clean Architecture / Ports and Adapters 思想。层次不要求运行时按
Interfaces → Application → Domain → Infrastructure 串行经过；应检查源码依赖与实际职责。
Application 可以直接使用 Domain 规则，并通过能力契约调用外部实现。
Infrastructure 不应反向依赖 HTTP Router。顶层目录不按重构阶段编号。

Application 的目标规划如下，仅用于 R2 设计；R1.1 不创建这些目录或实现：

```text
application/
├── agent/
│   ├── assistant/
│   ├── workflows/
│   ├── llm/
│   ├── tools/
│   ├── memory/
│   └── rag/
├── use_cases/
└── ports/
```

Workflow 管状态和执行，LLM 组件管 Prompt/结构化输出，Tools 暴露应用能力，Use Cases
承载可复用业务操作，Ports 表达实际需要的外部能力。Memory/RAG 在 R2 仅建立职责说明，
当前没有实现；不得提前开发占位伪实现。

## 设计判断

- 高内聚：内部模块按实际业务职责命名；同用 FastAPI 不意味着健康检查和日程必须放在同一文件。
- 低耦合和稳定依赖：不让业务核心因数据库、模型或通信框架替换而大改；也不为每次调用额外套接口。
- 适度抽象：只有独立职责、稳定契约或实际替换价值才支持新增抽象。避免一函数一 Service、一类一 Interface、无用途 Factory、单次转发包装和未来伪实现。
- 结构服务于查找：先用通用架构名组织顶层，再用业务名组织内部；不把简单操作拆成大量必须跳转的文件。
- 兼容层是迁移工具：只重导出同一实现，明确内部调用迁移计划；新主实现不依赖兼容入口，已承诺的公开入口继续支持。
- 先解释现有问题，再决定拆分；若少量更清晰的文件已足够，不机械照搬推荐目录。

## 可靠性不可因结构整理退化

区分 LLM 意图与可信事实、Graph State 与业务状态，以及 Request/Thread/Message/Operation ID。
区分模型建议、用户授权、执行结果和可验证的执行证据。
保留人工审批、稳定 Operation ID、事务与幂等、版本检查、owner 归属与跨用户隔离、
超时后对账和 Checkpointer 重启恢复。Domain 不混入 Graph State、LLM 输出或 HTTP 模型。

## 工作方法与裁决边界

每轮依次完成：分析职责问题 → 给出划分/依赖/兼容/验证方案 → 检查多余文件和抽象 →
执行有依据的最小重构 → 报告组织理由、替代方案和权衡。
普通内部拆分、命名、组织可在任务范围内自主判断；采用替代方案时说明原问题、职责边界、
收益、对公开行为与 R2 的影响及验证方式。
改变四层模型、两个独立 FastAPI App、业务语义或公开接口的设计须先报告并等待审核。
R1.1 冻结 Application，不迁移 Workflow、Tools、Graph State、Prompt、LLM 契约、用例或 Ports。
