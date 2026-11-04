# 文档索引

R2：[Application 设计审计与 D1–D6 批准条件](R2_A_APPLICATION_DESIGN_AUDIT.md) · [B0 兼容基线、Checkpoint 与故障语义](R2_B0_COMPATIBILITY_BASELINE.md) · [B1 读取与日程能力](R2_B1_READ_CALENDAR_REFACTOR.md) · [B2 可靠创建与审批](R2_B2_RELIABLE_CREATION.md)。B3–B6 仍须单独授权。

B0.1：[Prompt Gate 缺口更正、运行时采集与负向/搬家控制](R2_B0_1_PROMPT_GATE_FIX.md)。原始 B0 的 AST 字符串快照不能证明 Assistant/Natural Language Prompt 完整兼容。

当前架构阶段 R2-B2：[长期设计原则](ARCHITECTURE_PRINCIPLES.md) · [当前有效架构](architecture.md)。历史 [R1.1 收尾](R1_1_ARCHITECTURE_CLOSEOUT.md)、[R1 实施计划](R1_IMPLEMENTATION_PLAN.md)和[原始验收](R1_ARCHITECTURE_REFACTOR.md)保留原文。

TASK 08：[M9身份降级修复与收尾](TASK_08_M9_CLOSURE.md) · [M10最终集成/清洁启动/恢复证据（Docker未验证）](TASK_08_FINAL_DELIVERY.md)。

TASK 07：[M8受限范围](TASK_07_M8_SCOPE.md) · [M9测试账号、资源隔离与重启验收](TASK_07_M9_SECURITY.md)。

TASK 06-B：[M8真实模型验收、失败与交付门槛](audits/TASK_06B_2026-11-03.md)，当前为部分完成。

TASK 06（M8）：[业务操作、HTTP 契约与 Web 演示](TASK_06_BUSINESS_OPERATIONS.md) · [实施与验收证据](audits/TASK_06_2026-11-03.md)。代码待审核，未 Push。

当前：[项目运行与演示](../README.md) · [真实 Qwen 验收](ONLINE_VALIDATION.md)。历史工程基线：[运行方法](ENGINEERING_BASELINE.md) · [TASK 02 集成验收](audits/TASK_02_2026-11-02.md)。

| 阅读目的 | 文档 |
|---|---|
| 接手与约束 | [项目交接](PROJECT_HANDOFF.md)、[协作约定](../AGENTS.md)、[本轮任务](TASK_01_CODEX_AUDIT.md) |
| 架构设计 | [架构](architecture.md)、[安全](SECURITY.md)、[gRPC 草案](grpc-interface.proto) |
| 开发与演示 | [项目 README](../README.md)、[API](API.md)、[演示](DEMO.md) |
| 测试验收 | [验收矩阵](ACCEPTANCE_MATRIX.md)、[证据入口](EVALUATION.md)、[当前审计](audits/TASK_01_2026-11-02.md) |
| 规划与沿革 | [里程碑](milestones.md)、[能力映射](JD_MAPPING.md)、[开发沿革](ownership.md) |
| 历史 | [M2](history/M2.md)、[M3](history/M3.md)、[M4](history/M4.md)、[M5](history/M5.md)、[M6](history/M6.md)、[M7 旧验收](history/M7_EVALUATION_ORIGINAL.md)、[原只读任务](history/TASK_01_READONLY_ORIGINAL.md) |

保留既有路径作为稳定入口，新增 `audits/` 存放证据与决策。历史材料不代表当前验收；迁移清单和最终目录见本轮审计。
