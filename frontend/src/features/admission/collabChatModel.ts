// agent-collab/v1 → 主 agent 对话转写：主席（或系统编排）是对话里的主 agent，
// 评审/评分 agent 是它 spawn 出来的子 agent——子活动折叠为紧凑内联行，点开看细节。
// 消息体复用问答的 ChatMessage/ChatSegment（markdown + ToolCallCard）。纯函数：
// 实时跟随与回放共用同一解释逻辑，重复 event_id 幂等跳过；evidence_repair 归并评分实例。
import type { ChatSegment, CollabEvent } from "@/lib/types";
import { roleNames } from "./agentActivityModel";

export type SpawnState = "running" | "done" | "failed";

type ToolSegment = Extract<ChatSegment, { type: "tool" }>;

/** 一个被 spawn 的子 agent 的完整回合：派工目标 + 工具/说明 + 结论。 */
export interface CollabSpawn {
  key: string;
  role: string;
  name: string;
  goal: string;
  state: SpawnState;
  tools: ToolSegment[];
  notes: string[];
  result: { text: string; succeeded: boolean } | null;
}

export type CollabEntry =
  | { kind: "system"; key: string; at: string | null; text: string; tone: "info" | "success" | "error" }
  /** 主 agent 发言（自然语言，问答同款渲染） */
  | { kind: "lead"; key: string; at: string | null; variant: "speech"; text: string }
  /** 主 agent 亲自调用的工具（问答同款工具卡） */
  | { kind: "lead"; key: string; at: string | null; variant: "tool"; tool: ToolSegment }
  /** 历史（v1 JSON 派工时代）规划行 */
  | { kind: "lead"; key: string; at: string | null; variant: "planning"; round: number; contextCount: number }
  | { kind: "spawn"; key: string; at: string | null; spawnKey: string; birthEvent: string };

export interface CollabChatTaskStats {
  pending: number;
  active: number;
  done: number;
  failed: number;
}

export interface CollabChatTranscript {
  runState: "starting" | "running" | "completed" | "failed" | "cancelled";
  entries: CollabEntry[];
  spawns: CollabSpawn[];
  tasks: CollabChatTaskStats;
}

const TOOL_LABELS: Record<string, string> = {
  list_files: "盘点材料", read_text: "读取文本", read_pages: "视觉转译",
  search_text: "检索内容", verify_paper: "论文查证", web_search: "全网检索",
};

/** evidence_repair 与 task_score 是同一个评分 Agent 的重评回合（兼容归并前的历史事件）。 */
const normInstance = (id: string): string =>
  id.startsWith("evidence_repair:") ? "task_score:" + id.slice("evidence_repair:".length) : id;

/** 可解析的 JSON 摘要渲染为代码块（panel findings 摘要是 JSON 截断串），普通文本原样。 */
export function digestMarkdown(text: string): string {
  const trimmed = text.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      return "```json\n" + JSON.stringify(JSON.parse(trimmed), null, 2) + "\n```";
    } catch {
      // 截断的 JSON：按普通文本展示
    }
  }
  return text || "（未记录内容）";
}

export function reduceCollabChat(events: CollabEvent[]): CollabChatTranscript {
  const applied = new Set<string>();
  const entries: CollabEntry[] = [];
  const spawns = new Map<string, CollabSpawn>();
  const roles = new Map<string, string>();
  const tasks: CollabChatTaskStats = { pending: 0, active: 0, done: 0, failed: 0 };
  let runState: CollabChatTranscript["runState"] = "starting";
  let seq = -1;

  const spawnOf = (rawId: string, role: string, eventId = ""): CollabSpawn | null => {
    const id = normInstance(rawId);
    if (!id || id === "chair" || id === "system" || role === "chair" || role === "system") return null;
    let spawn = spawns.get(id);
    if (!spawn) {
      spawn = { key: id, role, name: "", goal: "", state: "running", tools: [], notes: [], result: null };
      spawns.set(id, spawn);
      roles.set(id, role);
      entries.push({ kind: "spawn", key: `spawn:${id}`, at: null, spawnKey: id, birthEvent: eventId });
    }
    return spawn;
  };
  // 主 agent 亲自调用的工具：call_id → 条目，tool.completed 原地更新状态
  const leadTools = new Map<string, Extract<CollabEntry, { kind: "lead"; variant: "tool" }>>();

  for (const envelope of events) {
    if (applied.has(envelope.event_id)) continue;
    applied.add(envelope.event_id);
    seq = envelope.seq;
    const { event, at } = envelope;
    const senderId = normInstance(envelope.instance_id || event.sender || "");
    const senderRole = envelope.agent_type || event.agent_type || "";
    const isLead = senderId === "chair" || senderRole === "chair";

    switch (event.type) {
      case "run.started":
        runState = "running";
        entries.push({ kind: "system", key: envelope.event_id, at, text: "协作开始", tone: "info" });
        break;
      case "run.completed":
        runState = "completed";
        for (const spawn of spawns.values()) if (spawn.state === "running") spawn.state = "done";
        entries.push({ kind: "system", key: envelope.event_id, at, text: "评估完成", tone: "success" });
        break;
      case "run.failed":
        runState = "failed";
        entries.push({ kind: "system", key: envelope.event_id, at,
          text: `评估中断：${typeof event.error === "string" ? event.error : "执行出现异常"}`, tone: "error" });
        break;
      case "run.cancelled":
        runState = "cancelled";
        entries.push({ kind: "system", key: envelope.event_id, at, text: "评估已停止", tone: "info" });
        break;
      case "instance.created":
        spawnOf(senderId, senderRole || event.agent_type || "", envelope.event_id);
        break;
      case "planning.started":
        entries.push({ kind: "lead", key: envelope.event_id, at,
          variant: "planning", round: Number(event.round_no ?? 1),
          contextCount: Array.isArray(event.context) ? event.context.length : 0 });
        break;
      case "task.dispatched": {
        const receiverId = normInstance(event.receiver || "");
        tasks.pending += 1;
        const spawn = spawnOf(receiverId, event.mission_type || "", envelope.event_id);
        const instruction = typeof event.instruction === "string" ? event.instruction.trim() : "";
        if (spawn && instruction) spawn.goal = instruction;
        break;
      }
      case "task.started": {
        const spawn = spawnOf(senderId, senderRole);
        if (spawn) spawn.state = spawn.state === "running" ? "running" : spawn.state;
        if (tasks.pending > 0) tasks.pending -= 1;
        tasks.active += 1;
        break;
      }
      case "tool.started": {
        const tool = typeof event.tool === "string" ? event.tool : "";
        const segment: ToolSegment = {
          type: "tool",
          call_id: typeof event.call_id === "string" ? event.call_id : `${seq}`,
          tool,
          label: TOOL_LABELS[tool] || tool || "工具调用",
          args_summary: typeof event.args_summary === "string" ? event.args_summary : "",
        };
        if (isLead) {
          const entry: Extract<CollabEntry, { kind: "lead"; variant: "tool" }> = {
            kind: "lead", key: envelope.event_id, at, variant: "tool", tool: segment,
          };
          leadTools.set(segment.call_id, entry);
          entries.push(entry);
          break;
        }
        const spawn = spawnOf(senderId, senderRole);
        if (spawn) spawn.tools.push(segment);
        break;
      }
      case "tool.completed": {
        const callId = String(event.call_id);
        const segment = leadTools.get(callId)?.tool
          ?? spawns.get(senderId)?.tools.find(s => s.call_id === callId);
        if (segment) {
          segment.status = event.status === "error" ? "error" : "ok";
          segment.summary = typeof event.summary === "string" ? event.summary : "";
        }
        break;
      }
      case "message.completed": {
        const text = typeof event.text === "string" ? event.text.trim() : "";
        if (!text) break;
        if (isLead) {
          // 主 agent 的正式发言
          entries.push({ kind: "lead", key: envelope.event_id, at, variant: "speech", text });
          break;
        }
        const spawn = spawnOf(senderId, senderRole);
        if (spawn) spawn.notes.push(text);
        break;
      }
      case "result.returned": {
        const succeeded = event.succeeded !== false;
        const digest = typeof event.digest === "string" ? event.digest.trim() : "";
        if (isLead) {
          // 历史（v1）：主席收队综合意见按主 agent 发言渲染
          entries.push({ kind: "lead", key: envelope.event_id, at, variant: "speech", text: digest });
          break;
        }
        const spawn = spawnOf(senderId, senderRole);
        if (spawn) {
          spawn.result = { text: digest, succeeded };
          spawn.state = succeeded ? "done" : "failed";
        }
        break;
      }
      case "task.completed": {
        const spawn = spawns.get(senderId);
        if (spawn) spawn.state = spawn.state === "failed" ? "failed" : "done";
        if (tasks.active > 0) tasks.active -= 1;
        tasks.done += 1;
        break;
      }
      case "task.failed": {
        const spawn = spawns.get(senderId);
        if (spawn) spawn.state = "failed";
        if (tasks.active > 0) tasks.active -= 1;
        tasks.failed += 1;
        break;
      }
      default:
        break;
    }
  }

  // 命名：同角色多实例时用 id 尾段消歧（如多个任务评分 Agent）
  const roleCount = new Map<string, number>();
  for (const role of roles.values()) roleCount.set(role, (roleCount.get(role) ?? 0) + 1);
  for (const spawn of spawns.values()) {
    const base = roleNames[spawn.role] || spawn.key;
    spawn.name = (roleCount.get(spawn.role) ?? 0) > 1 ? `${base}·${spawn.key.includes(":") ? spawn.key.split(":").pop()! : spawn.key}` : base;
  }

  return {
    runState,
    entries,
    spawns: [...spawns.values()],
    tasks,
  };
}
