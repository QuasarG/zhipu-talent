// 协作对话转写冒烟验证：主 agent 发言/工具 + 子 agent spawn 分组 + 历史事件归并 + 幂等回放
// （node --import tsx scripts/verify-collab-chat.mts）
import { digestMarkdown, reduceCollabChat } from "../src/features/admission/collabChatModel";
import type { CollabEvent } from "../src/lib/types";

let seq = -1;
const ev = (instance_id: string | null, event: Record<string, unknown>, extra: Partial<CollabEvent> = {}): CollabEvent => ({
  protocol: "agent-collab/v1", run_id: "r1", run_kind: "panel", event_id: `e${++seq}`, seq,
  at: "2026-09-11T03:00:00.000Z", instance_id, agent_type: null, task_id: null, task_kind: null,
  turn_no: null, message_id: null, cause_event_id: null, event: { type: "", ...event }, ...extra,
});

// —— panel v2：主席发言/亲自工具 + spawn 子评审 agent ——
const events: CollabEvent[] = [
  ev("chair", { type: "run.started" }, { agent_type: "chair" }),
  ev("m1", { type: "instance.created" }, { agent_type: "generic" }),
  ev("m2", { type: "instance.created" }, { agent_type: "generic" }),
  ev("chair", { type: "task.dispatched", sender: "chair", receiver: "m1", instruction: "精读代表作 paper.pdf，输出评审报告" },
    { agent_type: "chair", task_id: "m1", turn_no: 1 }),
  ev("m1", { type: "task.started" }, { agent_type: "generic" }),
  ev("m1", { type: "tool.started", call_id: "c1", tool: "read_pages", args_summary: "paper.pdf 第 1-3 页" }, { agent_type: "generic" }),
  ev("m1", { type: "tool.completed", call_id: "c1", tool: "read_pages", status: "ok", summary: "转译 3 页" }, { agent_type: "generic" }),
  ev("m1", { type: "message.completed", receiver: "chair", text: "## 发现\n方法细节充分" }, { agent_type: "generic" }),
  ev("m1", { type: "result.returned", receiver: "chair", digest: "技术深度 4 分", succeeded: true }, { agent_type: "generic" }),
  ev("m1", { type: "task.completed" }, { agent_type: "generic" }),
  ev("chair", { type: "task.dispatched", sender: "chair", receiver: "m2", instruction: "精读第二篇" },
    { agent_type: "chair", task_id: "m2", turn_no: 1 }),
  ev("m2", { type: "task.started" }, { agent_type: "generic" }),
  ev("m2", { type: "task.failed", error: "读取超时" }, { agent_type: "generic" }),
  ev("chair", { type: "tool.started", call_id: "ct1", tool: "read_text", args_summary: "简历.docx 第 1 段" }, { agent_type: "chair" }),
  ev("chair", { type: "tool.completed", call_id: "ct1", tool: "read_text", status: "ok", summary: "读取 400 字" }, { agent_type: "chair" }),
  ev("chair", { type: "message.completed", text: "两份深读报告已收齐，开始汇总结论。" }, { agent_type: "chair" }),
  ev("chair", { type: "result.returned", receiver: "system", digest: '{"per_jd":[]}' }, { agent_type: "chair" }),
  ev("chair", { type: "run.completed" }, { agent_type: "chair" }),
];

const room = reduceCollabChat(events);
const kinds = room.entries.map(e => e.kind);
console.assert(room.runState === "completed", "终态 completed");
console.assert(kinds[0] === "system" && kinds[kinds.length - 1] === "system", "开场/收尾系统胶囊");

const speeches = room.entries.filter(e => e.kind === "lead" && e.variant === "speech");
console.assert(speeches.length === 2, "主 agent 发言两条（一句陈述 + 一份综合意见）");
console.assert(speeches.some(s => s.text.includes("两份深读报告")), "自然语言发言入流");
console.assert(speeches.some(s => s.text.includes("per_jd")), "综合意见 digest 入流（渲染层转代码块）");

const leadTools = room.entries.filter(e => e.kind === "lead" && e.variant === "tool");
console.assert(leadTools.length === 1 && leadTools[0].tool.status === "ok" && leadTools[0].tool.label === "读取文本",
  "主席亲自工具是 lead 工具条目且状态落位");

console.assert(room.spawns.length === 2, "两个子 agent spawn");
const m1 = room.spawns.find(s => s.key === "m1")!;
console.assert(m1.goal === "精读代表作 paper.pdf，输出评审报告", "spawn 目标来自派工 prompt");
console.assert(m1.state === "done" && m1.result?.text === "技术深度 4 分", "spawn 结论与终态");
console.assert(m1.tools.length === 1 && m1.tools[0].status === "ok" && m1.tools[0].label === "视觉转译",
  "工具段挂在 spawn 上且带完成状态");
console.assert(m1.notes.length === 1 && m1.notes[0].includes("方法细节充分"), "工作说明挂在 spawn 上");
console.assert(m1.name === "通用评审员·m1", "同角色多实例消歧命名");
const m2 = room.spawns.find(s => s.key === "m2")!;
console.assert(m2.state === "failed", "失败 spawn 终态");
console.assert(room.tasks.done === 1 && room.tasks.failed === 1, "任务统计闭环");

const replay = reduceCollabChat(events);
console.assert(replay.spawns.length === room.spawns.length && replay.entries.length === room.entries.length, "重放幂等");
const mid = reduceCollabChat(events.slice(0, 8));
console.assert(mid.spawns.find(s => s.key === "m1")?.state === "running", "回放切片保持运行态");
console.assert(mid.spawns.find(s => s.key === "m1")?.tools.length === 1, "回放切片已见工具");
console.assert(digestMarkdown('{"a":1}').startsWith("```json"), "JSON digest 转代码块");

// —— 历史事件兼容：v1 规划行 + repair/score 分离实例 ——
const legacy: CollabEvent[] = [
  ev("chair", { type: "planning.started", round_no: 2, context: [{}] }, { agent_type: "chair" }),
  ev("task_score:t9", { type: "instance.created" }, { agent_type: "task_scorer" }),
  ev("evidence_repair:t9", { type: "instance.created" }, { agent_type: "task_scorer" }),
  ev("evidence_repair:t9", { type: "result.returned", receiver: "system", digest: "证据修正后评定 3 级", succeeded: true }, { agent_type: "task_scorer" }),
];
const legacyRoom = reduceCollabChat(legacy);
console.assert(legacyRoom.entries.some(e => e.kind === "lead" && e.variant === "planning" && e.round === 2),
  "历史规划行仍可渲染");
console.assert(legacyRoom.spawns.length === 1 && legacyRoom.spawns[0].key === "task_score:t9",
  "历史 repair 事件归并进评分实例");

console.log("collab-chat smoke: all assertions passed");
