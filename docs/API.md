# API Reference（本地演示）

启动服务：`python -m uvicorn productivity_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000`

REST API 的官方 OpenAPI 页面：<http://127.0.0.1:8000/docs>。若设置了 `PPA_API_TOKEN`，请在请求头加 `X-PPA-Token: <token>`；这只是本地演示共享 Token，不是用户身份认证。

## 检查日历（不写入）

```powershell
$body = @{
  request = @{
    title = "组会"
    start_at = "2026-12-10T15:00:00+08:00"
    end_at = "2026-12-10T16:00:00+08:00"
  }
  busy_slots = @(@{
    start_at = "2026-12-10T15:30:00+08:00"
    end_at = "2026-12-10T16:30:00+08:00"
  })
} | ConvertTo-Json -Depth 10
Invoke-RestMethod 'http://127.0.0.1:8000/v1/calendar/check' -Method POST -Body $body -ContentType 'application/json'
```

返回：`{"result":{"status":"conflict","suggested_start":"2026-12-10T16:30:00+08:00",...}}`。

SSE 端点 `/v1/calendar/check/stream` 接受相同 JSON，事件以 `event: progress`、`event: done` 返回；`done` 返回的是工作流结果，不包含后端任务写入。

## 创建并审批本地任务

```powershell
$draft = Invoke-RestMethod 'http://127.0.0.1:8000/v1/tasks/drafts' -Method POST -ContentType 'application/json' -Body '{"title":"准备组会","due_at":"2026-12-10T15:00:00+08:00"}'
$draft.thread_id
Invoke-RestMethod "http://127.0.0.1:8000/v1/tasks/drafts/$($draft.thread_id)" -Method GET
Invoke-RestMethod "http://127.0.0.1:8000/v1/tasks/drafts/$($draft.thread_id)/decision" -Method POST -ContentType 'application/json' -Body '{"approved":true}'
Invoke-RestMethod 'http://127.0.0.1:8000/v1/tasks' -Method GET
```

再批准同一个已完成 Thread 应返回 HTTP 409，不会再次写入业务记录。跨进程恢复需保持 `.ppa-data` 持久化。

## 千问可选接口

开启 `PPA_ENABLE_LIVE_QWEN=1` 并配置百炼 Key 后，可使用：

- `POST /v1/calendar/natural-language`：`{"message":"明天下午三点安排一小时组会","reference_now":"2026-11-02T12:00:00+08:00","busy_slots":[]}`。
- `POST /v1/agent/ask`：`{"message":"查询明天日程","reference_now":"2026-11-02T12:00:00+08:00"}`。
- `POST /v1/agent/stream`：同上，但以 SSE 返回节点进度。

时间必须携带 UTC 偏移（如 `+08:00`）；模型可能误解自然语言，结构校验不能替代业务核实。所有这些接口使用**模拟业务工具**，没有真实日历写入权限。

## HTTP 错误

- `401`：配置了演示 Token 但未提供或不匹配。
- `404`：不存在的 Thread。
- `409`：重复审批已经完成的 Thread。
- `422`：不符合 Pydantic Schema 的请求。
- `503`：未开启千问模式。
- `502`：模型解析接口异常（隐藏供应商内部异常以避免泄露信息）。
