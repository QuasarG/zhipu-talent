// agent-collab/v1 → 群聊转写：把协作事件流折叠为聊天室消息。
// 消息体复用问答的 ChatMessage/ChatSegment（markdown + ToolCallCard），
// 由 AgentGroupChat 的消息行渲染。纯函数：实时跟随与回放共用同一解释逻辑，
// 重复 event_id 幂等跳过；主席派工 = 主席的聊天消息，评审员回传 = 评审员的聊天消息。
import type { ChatMessage, ChatSegment, CollabEvent } from "@/lib/types";
import { roleNames } from "./agentActivityModel";

export type ChatMemberState = "waiting" | "working" | "done" | "failed";

export interface ChatMember {
  id: string;
  role: string;
  name: string;
  state: ChatMemberState;
}

export interface CollabChatEntry {
  kind: "system" | "planning" | "chat";
  key: string;
  at: string | null;
  senderId: string;
  senderName: string;
  /** 消息行徽章：派工 / 结论回传 / 综合意见 / 失败回传 */
  badge?: string;
  badgeTone?: "primary" | "success" | "error" | "neutral";
  /** 派工 @ 接收者（成员可能尚未创建，命名在收尾阶段解析） */
  mentionId?: string;
  mentionName?: string;
  /** system/planning 行文案 */
  text?: string;
  tone?: "info" | "success" | "error";
  round?: number;
  contextCount?: number;
  succeeded?: boolean;
  message: ChatMessage;
}

export interface CollabChatTaskStats {
  pending: number;
  active: number;
  done: number;
  failed: number;
}

export interface CollabChatTranscript {
  runState: "starting" | "running" | "completed" | "failed" | "cancelled";
  members: ChatMember[];
  entries: CollabChatEntry[];
  tasks: CollabChatTaskStats;
}

interface MemberDraft {
  id: string;
  role: string;
  state: ChatMemberState;
  order: number;
}

const TOOL_LABELS: Record<string, string> = {
  list_files: "盘点材料", read_text: "读取文本", read_pages: "视觉转译",
  search_text: "检索内容", verify_paper: "论文查证", web_search: "全网检索",
};

const emptyMessage = (id: string, segments: ChatSegment[], at: string | null): ChatMessage => ({
  id,
  conversation_id: "collab",
  role: "assistant",
  content: { segments },
  citations: [],
  status: "completed",
  created_at: at ?? "",
});

const shortId = (id: string): string => (id.includes(":") ? id.split(":").pop() || id : id);

/** 可解析的 JSON 摘要渲染为代码块（panel findings 摘要是 JSON 截断串），普通文本原样。 */
function digestSegment(text: string): ChatSegment {
  const trimmed = text.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      return { type: "text", text: "```json\n" + JSON.stringify(JSON.parse(trimmed), null, 2) + "\n```" };
    } catch {
      // 截断的 JSON：按普通文本展示
    }
  }
  return { type: "text", text: text || "（未记录内容）" };
}

export function reduceCollabChat(events: CollabEvent[]): CollabChatTranscript {
  const members = new Map<string, MemberDraft>();
  const entries: CollabChatEntry[] = [];
  const applied = new Set<string>();
  const tasks: CollabChatTaskStats = { pending: 0, active: 0, done: 0, failed: 0 };
  let runState: CollabChatTranscript["runState"] = "starting";
  // 每个成员的未落章工具段：随下一条消息/回传一起并入消息 segments
  const pendingTools = new Map<string, ChatSegment[]>();

  const member = (id: string, role: string): MemberDraft => {
    let draft = members.get(id);
    if (!draft) {
      draft = { id, role, state: "waiting", order: members.size };
      members.set(id, draft);
    }
    return draft;
  };
  const working = (id: string, role = "") => {
    const draft = member(id, role);
    if (draft.state !== "failed") draft.state = "working";
  };
  const flushTools = (senderId: string): ChatSegment[] => {
    const segments = pendingTools.get(senderId) ?? [];
    pendingTools.delete(senderId);
    return segments;
  };
  const pushTool = (senderId: string, segment: ChatSegment) => {
    const list = pendingTools.get(senderId) ?? [];
    list.push(segment);
    pendingTools.set(senderId, list);
  };

  for (const envelope of events) {
    if (applied.has(envelope.event_id)) continue;
    applied.add(envelope.event_id);
    const { event, instance_id: instanceId, at } = envelope;
    const senderId = instanceId || event.sender || "";
    const senderRole = envelope.agent_type || event.agent_type || "";
    const seq = envelope.seq;

    switch (event.type) {
      case "run.started":
        runState = "running";
        entries.push({ kind: "system", key: envelope.event_id, at, senderId: "", senderName: "",
          text: "协作开始", tone: "info", message: emptyMessage(envelope.event_id, [], at) });
        break;
      case "run.completed":
        runState = "completed";
        for (const draft of members.values()) if (draft.state === "working") draft.state = "done";
        entries.push({ kind: "system", key: envelope.event_id, at, senderId: "", senderName: "",
          text: "评估完成", tone: "success", message: emptyMessage(envelope.event_id, [], at) });
        break;
      case "run.failed":
        runState = "failed";
        entries.push({ kind: "system", key: envelope.event_id, at, senderId: "", senderName: "",
          text: `评估中断：${typeof event.error === "string" ? event.error : "执行出现异常"}`, tone: "error",
          message: emptyMessage(envelope.event_id, [], at) });
        break;
      case "run.cancelled":
        runState = "cancelled";
        entries.push({ kind: "system", key: envelope.event_id, at, senderId: "", senderName: "",
          text: "评估已停止", tone: "info", message: emptyMessage(envelope.event_id, [], at) });
        break;
      case "instance.created":
        member(senderId, senderRole || event.agent_type || "");
        break;
      case "planning.started": {
        member(senderId || "chair", "chair");
        entries.push({ kind: "planning", key: envelope.event_id, at, senderId: senderId || "chair",
          senderName: "", round: Number(event.round_no ?? 1),
          contextCount: Array.isArray(event.context) ? event.context.length : 0,
          message: emptyMessage(envelope.event_id, [], at) });
        break;
      }
      case "task.dispatched": {
        const receiverId = event.receiver || "";
        const receiver = members.get(receiverId);
        if (receiver) receiver.state = receiver.state === "failed" ? "failed" : "waiting";
        if (receiverId && !receiver) member(receiverId, event.mission_type || "");
        tasks.pending += 1;
        const lines: string[] = [];
        const instruction = typeof event.instruction === "string" ? event.instruction.trim() : "";
        if (instruction) lines.push(instruction);
        const files = Array.isArray(event.files) ? event.files.filter(f => typeof f === "string") as string[] : [];
        if (files.length) lines.push(`材料：${files.join("、")}`);
        const questions = Array.isArray(event.questions) ? event.questions.filter(q => typeof q === "string") as string[] : [];
        if (questions.length) lines.push(`问题：\n${questions.map(q => `- ${q}`).join("\n")}`);
        const note = typeof event.note === "string" ? event.note.trim() : "";
        if (note) lines.push(`续派指令：${note}`);
        entries.push({ kind: "chat", key: envelope.event_id, at, senderId: senderId || "chair", senderName: "",
          badge: "派工", badgeTone: "primary", mentionId: receiverId,
          message: emptyMessage(envelope.event_id, [{ type: "text", text: lines.join("\n\n") || "（见任务）" }], at) });
        break;
      }
      case "task.started": {
        working(senderId, senderRole);
        if (tasks.pending > 0) tasks.pending -= 1;
        tasks.active += 1;
        break;
      }
      case "tool.started": {
        working(senderId, senderRole);
        const tool = typeof event.tool === "string" ? event.tool : "";
        pushTool(senderId, {
          type: "tool", call_id: typeof event.call_id === "string" ? event.call_id : `${seq}`,
          tool, label: TOOL_LABELS[tool] || tool || "工具调用",
          args_summary: typeof event.args_summary === "string" ? event.args_summary : "",
        });
        break;
      }
      case "tool.completed": {
        const list = pendingTools.get(senderId);
        const segment = list?.find(s => s.type === "tool" && s.call_id === event.call_id) as
          | Extract<ChatSegment, { type: "tool" }> | undefined;
        if (segment) {
          segment.status = event.status === "error" ? "error" : "ok";
          segment.summary = typeof event.summary === "string" ? event.summary : "";
        }
        break;
      }
      case "message.completed": {
        working(senderId, senderRole);
        const text = typeof event.text === "string" ? event.text : "";
        if (!text.trim() && !pendingTools.get(senderId)?.length) break;
        entries.push({ kind: "chat", key: envelope.event_id, at, senderId, senderName: "",
          message: emptyMessage(envelope.event_id,
            [...flushTools(senderId), ...(text.trim() ? [{ type: "text" as const, text }] : [])], at) });
        break;
      }
      case "result.returned": {
        const sender = members.get(senderId);
        if (sender && sender.state !== "failed") sender.state = "done";
        const receiverId = typeof event.receiver === "string" ? event.receiver : "system";
        const receiver = members.get(receiverId);
        if (receiver && receiver.id !== senderId && receiver.state !== "failed") receiver.state = "working";
        const succeeded = event.succeeded !== false;
        const digest = typeof event.digest === "string" ? event.digest : "";
        const synthesis = receiverId === "system" && senderId === "chair";
        entries.push({ kind: "chat", key: envelope.event_id, at, senderId, senderName: "",
          badge: synthesis ? "综合意见" : succeeded ? "结论回传" : "失败回传",
          badgeTone: synthesis ? "neutral" : succeeded ? "success" : "error",
          succeeded,
          message: emptyMessage(envelope.event_id, [...flushTools(senderId), digestSegment(digest)], at) });
        break;
      }
      case "task.completed": {
        const draft = members.get(senderId);
        if (draft && draft.state !== "failed") draft.state = "done";
        if (tasks.active > 0) tasks.active -= 1;
        tasks.done += 1;
        const rest = flushTools(senderId);
        if (rest.length) entries.push({ kind: "chat", key: envelope.event_id, at, senderId, senderName: "",
          message: emptyMessage(envelope.event_id, rest, at) });
        break;
      }
      case "task.failed": {
        const draft = members.get(senderId);
        if (draft) draft.state = "failed";
        if (tasks.active > 0) tasks.active -= 1;
        tasks.failed += 1;
        const error = typeof event.error === "string" ? event.error : "任务执行失败";
        entries.push({ kind: "chat", key: envelope.event_id, at, senderId, senderName: "",
          badge: "失败回传", badgeTone: "error", succeeded: false,
          message: emptyMessage(envelope.event_id, [...flushTools(senderId), digestSegment(error)], at) });
        break;
      }
      default:
        break;
    }
  }

  // 命名：同角色多实例时用 id 尾段消歧（如多个任务评分 Agent）
  const roleCount = new Map<string, number>();
  for (const draft of members.values()) roleCount.set(draft.role, (roleCount.get(draft.role) ?? 0) + 1);
  const nameOf = (id: string): string => {
    const draft = members.get(id);
    const role = draft?.role || "";
    if (!draft) return id === "system" ? "系统调度" : id === "chair" ? roleNames.chair : id;
    const base = roleNames[role] || shortId(id);
    return (roleCount.get(role) ?? 0) > 1 ? `${base}·${shortId(id)}` : base;
  };
  for (const entry of entries) {
    entry.senderName = entry.kind === "system" ? ""
      : entry.kind === "planning" ? nameOf(entry.senderId)
        : nameOf(entry.senderId);
    if (entry.mentionId) {
      const mention = members.get(entry.mentionId);
      entry.mentionName = mention ? nameOf(entry.mentionId) : entry.mentionId;
    }
  }

  // 仍在执行的工具段：立即以运行态消息出现在群里（ToolCallCard 呈现进行中动效），
  // 落章后并入对应的消息/回传行；key 稳定，成员未发言时也能看到工具活动。
  for (const [senderId, segments] of pendingTools) {
    if (!segments.length) continue;
    entries.push({ kind: "chat", key: `pending:${senderId}`, at: null, senderId, senderName: "",
      message: emptyMessage(`pending:${senderId}`, segments, null) });
  }

  return {
    runState,
    members: [...members.values()]
      .sort((a, b) => a.order - b.order)
      .map(draft => ({ id: draft.id, role: draft.role, state: draft.state, name: nameOf(draft.id) })),
    entries,
    tasks,
  };
}
