# Agent 协作事件协议（agent-collab/v1）契约草案

状态：A 节梳理产出，待随 B 节实现修订。本文档服务于"动态二维工位"：前端不再从评估结果或节点日志猜协作关系，而是消费结构化协作事件。

## 1. 现状核对结论（2026-09-08）

### 链路与调度

| | 评审团（panel） | 准入（admission） |
|---|---|---|
| 入口 | `POST /api/persons/batch-evaluate`（workbench.py:1199，后台线程） | `POST /api/interview-assessment-batches`（interview_assessment_api.py:24） |
| 编排 | `run_panel_stream`（agents/job_fit/panel.py:510）主席 LLM 决策驱动 | `evaluate_candidate_for_job`（agents/interview_admission/evaluator.py:132）确定性代码驱动 |
| 调度者 | **主席 chair（真实 LLM 角划）** | **系统（确定性编排，无主席）** |
| 执行形态 | 串行：dispatch 循环逐个 `run_mission` | 并行：`_TASK_EXECUTOR` 线程池并行 `score_task` |
| 实例身份 | chair 固定；评审员=mission_id（主席命名，续派复用同 id=同一实例） | mapper / task_scorer(`task_score:<task_id>`) / reviewer / system，由 node_id 推断（evaluator.py:113-118） |
| 消息收发 | 派工=dispatch 事件（panel.py:579）；回传=handoff 事件+findings 摘要（panel.py:594） | 事件 dict 直传，无消息对象；scorer 完成→`handoff` to system（evaluator.py:304-313） |
| 工具调用 | 有：`call_llm_tools` + `_execute_tool`（读材料/验论文/搜索，panel.py:149-185,387-396） | 无 LLM 工具；证据反查是确定性代码（evaluator.py:425） |
| 流式能力 | `call_llm_tools` 支持流式但 panel 未接 `on_delta`（panel.py:369）→ 正文整段出现 | 全部 `call_llm_json` 非流式 |
| 事件出口（单点） | `node()`/`lead_node()`（panel.py:341/519） | `_Trace.event`（evaluator.py:87） |
| 实时落库 | `record_node_event` 逐条 commit，append 进 `evaluations.panel_trace` JSON 列（repository.py:133-192），**400 条截断** | `_append_run_event` 逐条 commit，append 进 run 行 `run_trace` JSON 列（service.py:398-406） |
| 前端通道 | 3s 轮询 `GET /api/candidates/<id>` | 1.2s 轮询批次/活动 run |

chat 问答链路（对照）：SSE `POST /api/knowledge/ask`，事件 `{type,payload}`：`meta / answer_delta / thinking_delta / tool_start / tool_end / action_required / sources / message_done / done / error`（knowledge_agent/agent.py:129-310）。**token 级增量目前只有这条链有。**

### 首个端到端验证入口

**评审团链路（panel）**。理由：主席、派工/接收/回传、工具调用、续派、轮次全部真实存在，埋点集中在两个出口函数；动态工位所需的全部协作语义都能真实产生。准入链路并行/失败恢复场景随后接入（保留系统调度语义，不加主席）。

### 缺口清单（现有代码不存在、需 B 节补充）

1. 事件唯一 `event_id` 与运行内单调 `seq`；无 append-only 事件表（宿主行 JSON 整读整写，panel 还有 400 条截断）。
2. 通用收发方字段：仅 dispatch/handoff 带 `target_id`；status/message/tool 事件无接收方语义。
3. 派发与开始执行的区分：panel 有（dispatch vs request），admission 无（`task_score` running 事件兼任两者；排队→运行的转换只落在 DB status）。
4. 公开文本增量：panel 正文整段（未接 `on_delta`）；admission 非流式。无增量能力的阶段按真实状态呈现，不做假打字。
5. 轮次/尝试号未入事件：panel 的 `round_no`、mission 重试 attempt 在内存中；admission 前端类型声明的 `turn/attempt` 后端不产出。
6. 因果 ID：admission 有 node 级 `parent_id`；panel 无（靠 mission_id 字符串匹配）；跨链路无统一 run 概念（admission 事件的 run_id 是内存 uuid，≠ DB 行 id）。
7. 产物引用：findings/task_assessment 等结果对象与事件之间无引用键。

## 2. 身份与关联模型

| 概念 | 字段 | 取值来源 |
|---|---|---|
| 运行 | `run_id` + `run_kind` | panel: `evaluations.id`；admission: `interview_assessment_runs.id`（用 DB 行 id，不用内存 uuid） |
| Agent 实例 | `instance_id` + `agent_type` | panel: `chair` / mission_id + 五类工种；admission: `capability_mapping`(mapper) / `task_score:<tid>`(task_scorer) / `overall_review`(reviewer) / `system` |
| 任务 | `task_id` + `task_kind` | panel: mission_id（kind=mission）；admission: node_id（kind=mapping/score/review/decision） |
| 轮次 | `turn_no` | panel: 主席 dispatch 轮（现成 `round_no`）+ 实例续派轮（lifetime 计数）；admission: 任务恒为 1 |
| 消息 | `message_id` + `reply_to` | 有明确收发方的信息传递；handoff 消息 reply_to 其响应的 dispatch 消息 |
| 工具调用 | `call_id` | panel 已有；挂 instance + task |
| 产物 | `artifact_id` + `kind` + `digest` | panel: findings；admission: task_assessment / review_corrections / staged_result。事件只带摘要与引用，正文入既有结果存储 |

实例生命周期：`created`（首次出现于事件流）→ `active` → `finished | failed`。**panel 续派复用 instance_id，不新建实例，turn_no 递增。**

## 3. 事件信封

```json
{
  "protocol": "agent-collab/v1",
  "run_id": "123",
  "run_kind": "panel",
  "event_id": "b3c1…uuid4",
  "seq": 42,
  "at": "2026-09-08T15:04:05.123+08:00",
  "instance_id": "m1",
  "agent_type": "verify",
  "task_id": "m1",
  "task_kind": "mission",
  "turn_no": 1,
  "message_id": null,
  "cause_event_id": "…uuid4",
  "event": { "type": "…", "…": "…" }
}
```

- `seq`：运行内 0 起单调递增，写入端在事务内分配（配合行锁/单写入线程），读取端用于断线补齐与去重。
- `cause_event_id`：直接因果（`task.received`←`task.dispatched`；`result.returned`←`task.received`；`message.delta`←`message.started`）。
- 无对应字段的事件置 null；`system` 实例不假扮 Agent（前端用系统视觉语义）。

## 4. 事件类型

生命周期与运行：`run.started`、`run.completed`、`run.failed`、`run.cancelled`。
主席规划（panel 专属）：`planning.started`、`planning.completed`（payload：`round_no`、决策摘要）。
实例与任务：

| type | 语义 | 关键 payload | panel 来源 | admission 来源 |
|---|---|---|---|---|
| `instance.created` | 实例创建 | mission_type, goal | 新 mission_id 首次 dispatch | 节点首次运行 |
| `task.dispatched` | 派工（≠开始执行） | message_id, target_instance_id, instruction, files, questions, reuse_context, reply_to | dispatch 事件 | （无主席：不产生；系统启动任务用 `task.started`） |
| `task.started` | 接收并开始执行 | cause=dispatched | request 事件 | 节点 running |
| `task.completed` / `task.failed` | 任务终态 | error, attempt | mission return | 节点 completed/failed |
| `result.returned` | 结果回传 | message_id, target_instance_id, artifact_id, digest, reply_to | handoff→chair | handoff→system |

消息：`message.started`（sender/receiver/任务轮次）、`message.delta`（text 增量，仅真实流式能力存在时）、`message.completed`。
工具：`tool.started`（call_id/tool/args_summary）、`tool.completed`（call_id/status/summary/detail）。

**派发与执行区分**：`task.dispatched` 只表示指令已发出；`task.started` 才表示实例已接收执行。排队中的任务两事件都不会有 `task.started`。

## 5. 真实事件序列样例（panel，chair→评审员→回传→续派）

```jsonl
{"protocol":"agent-collab/v1","run_id":"9001","run_kind":"panel","event_id":"e01","seq":0,"at":"…","instance_id":"chair","agent_type":"chair","event":{"type":"run.started"}}
{"…","event_id":"e02","seq":1,"instance_id":"chair","event":{"type":"planning.started","round_no":1}}
{"…","event_id":"e03","seq":2,"instance_id":"m1","agent_type":"verify","task_id":"m1","turn_no":1,"event":{"type":"instance.created","mission_type":"verify","goal":"核实项目贡献归属"}}
{"…","event_id":"e04","seq":3,"instance_id":"chair","message_id":"msg-77","cause_event_id":"e02","event":{"type":"task.dispatched","target_instance_id":"m1","instruction":"请核实项目说明中的贡献归属，标出原文依据。","files":["项目说明.pdf"],"reuse_context":false}}
{"…","event_id":"e05","seq":4,"instance_id":"m1","task_id":"m1","turn_no":1,"cause_event_id":"e04","event":{"type":"task.started"}}
{"…","event_id":"e06","seq":5,"instance_id":"m1","task_id":"m1","event":{"type":"tool.started","call_id":"c1","tool":"read_pages","args_summary":"项目说明.pdf 第3页"}}
{"…","event_id":"e07","seq":6,"instance_id":"m1","task_id":"m1","cause_event_id":"e06","event":{"type":"tool.completed","call_id":"c1","status":"ok","summary":"找到评测模块负责人说明"}}
{"…","event_id":"e08","seq":7,"instance_id":"m1","task_id":"m1","event":{"type":"message.started","message_id":"msg-78","sender":"m1","receiver":"chair"}}
{"…","event_id":"e09","seq":8,"instance_id":"m1","task_id":"m1","event":{"type":"message.completed","message_id":"msg-78"}}   // 当前无 on_delta：只有整段 completed，不伪造 delta
{"…","event_id":"e10","seq":9,"instance_id":"m1","task_id":"m1","turn_no":1,"event":{"type":"task.completed"}}
{"…","event_id":"e11","seq":10,"instance_id":"m1","message_id":"msg-79","cause_event_id":"e05","event":{"type":"result.returned","target_instance_id":"chair","artifact_id":"art-m1","digest":"已确认评测模块贡献；整体架构表述缺少支持。","reply_to":"msg-77"}}
{"…","event_id":"e12","seq":11,"instance_id":"chair","event":{"type":"planning.started","round_no":2}}
{"…","event_id":"e13","seq":12,"instance_id":"chair","message_id":"msg-80","event":{"type":"task.dispatched","target_instance_id":"m1","instruction":"续派：确认没有把待验证主张写成已确认事实。","reuse_context":true}}   // 续派：同 instance，无 instance.created
{"…","event_id":"e14","seq":13,"instance_id":"m1","task_id":"m1","turn_no":2,"cause_event_id":"e13","event":{"type":"task.started"}}
{"…","event_id":"e20","seq":19,"instance_id":"chair","event":{"type":"run.completed","summary":"综合意见已就绪"}}
```

## 6. 状态转换表

实例状态：`none → created →(task.started)→ working →(task.completed)→ idle →(续派 task.started)→ working … → finished(run 终态)`；`working →(task.failed)→ failed`。
任务状态：`dispatched → started → completed | failed`；无主席链路 `queued → started → …`。
消息状态：`started → delta* → completed`；仅整段能力时 `started → completed`。
恢复规则：前端按 `event_id` 去重、按 `seq` 补缺重放；重复输入不重复建实例（`instance.created` 幂等键 = run_id+instance_id）。

## 7. 待用户确认

准入链路当前是确定性系统编排（无主席）。若要"主席调度"视觉效果对应真实行为，需要把编排改为 LLM 主席决策——这会改变执行路径、耗时与成本，并触碰评分合同。**未确认前 admission 保持系统调度**，工位上系统节点用非 Agent 视觉语义呈现，不伪造主席。
