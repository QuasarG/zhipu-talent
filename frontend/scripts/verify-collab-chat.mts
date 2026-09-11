// 协作对话转写冒烟验证：主 agent 发言 + 子 agent spawn 分组 + 历史事件归并 + 幂等回放
// （node --import tsx scripts/verify-collab-chat.mts）
import { digestMarkdown, reduceCollabChat } from "../src/features/admission/collabChatModel";
import type { CollabEvent } from "../src/lib/types";

let seq = -1;
const ev = (instance_id: string | null, event: Record<string, unknown>, extra: Partial<CollabEvent> = {}): CollabEvent => ({
  protocol: "agent-collab/v1", run_id: "r1", run_kind: "panel", event_id: `e${++seq}`, seq,
  at: "2026-09-11T03:00:00.000Z", instance_id, agent_type: null, task_id: null, task_kind: null,
  turn_no: null, message_id: null, cause_event_id: null, event: { type: "", ...event }, ...extra,
});

// —— panel：主席派工 → 子评审员工具/说明/结论 → 主席收队 ——
const events: CollabEvent[] = [
  ev("chair", { type: "run.started" }, { agent_type: "chair" }),
  ev("chair", { type: "planning.started", round_no: 1, context: [] }, { agent_type: "chair" }),
  ev("m1", { type: "instance.created" }, { agent_type: "deep_read" }),
  ev("m2", { type: "instance.created" }, { agent_type: "deep_read" }),
  ev("chair", { type: "task.dispatched", sender: "chair", receiver: "m1", instruction: "精读代表作",
    files: ["paper.pdf"], questions: ["贡献边界?"] }, { agent_type: "chair", task_id: "m1", turn_no: 1 }),
  ev("m1", { type: "task.started" }, { agent_type: "deep_read" }),
  ev("m1", { type: "tool.started", call_id: "c1", tool: "read_pages", args_summary: "paper.pdf 第 1-3 页" }, { agent_type: "deep_read" }),
  ev("m1", { type: "tool.completed", call_id: "c1", tool: "read_pages", status: "ok", summary: "转译 3 页" }, { agent_type: "deep_read" }),
  ev("m1", { type: "message.completed", receiver: "chair", text: "## 发现\n方法细节充分" }, { agent_type: "deep_read" }),
  ev("m1", { type: "result.returned", receiver: "chair", digest: "技术深度 4 分", succeeded: true }, { agent_type: "deep_read" }),
  ev("m1", { type: "task.completed" }, { agent_type: "deep_read" }),
  ev("chair", { type: "task.dispatched", sender: "chair", receiver: "m2", instruction: "精读第二篇" }, { agent_type: "chair", task_id: "m2", turn_no: 1 }),
  ev("m2", { type: "task.started" }, { agent_type: "deep_read" }),
  ev("m2", { type: "task.failed", error: "读取超时" }, { agent_type: "deep_read" }),
  ev("chair", { type: "result.returned", receiver: "system", digest: '{"per_jd":[]}' }, { agent_type: "chair" }),
  ev("chair", { type: "run.completed" }, { agent_type: "chair" }),
];

const room = reduceCollabChat(events);
const kinds = room.entries.map(e => e.kind);
console.assert(room.runState === "completed", "终态 completed");
console.assert(kinds[0] === "system" && kinds[1] === "lead", "开场：开始胶囊 + 主席规划行");
console.assert(kinds[kinds.length - 1] === "system", "收尾：完成胶囊");
const planning = room.entries.filter(e => e.kind === "lead" && e.variant === "planning");
console.assert(planning.length === 1 && planning[0].round === 1, "规划行一条");
const speech = room.entries.find(e => e.kind === "lead" && e.variant === "speech");
console.assert(!!speech && speech.badge === "综合意见"
  && speech.message.content.segments.some(s => s.type === "text" && s.text.includes('"per_jd"')),
  "主席收队是主 agent 发言，JSON digest 走代码块");
console.assert(room.spawns.length === 2, "两个子 agent spawn");
const m1 = room.spawns.find(s => s.key === "m1")!;
console.assert(m1.goal === "精读代表作", "spawn 目标来自派工指令");
console.assert(m1.state === "done" && m1.result?.text === "技术深度 4 分", "spawn 结论与终态");
console.assert(m1.tools.length === 1 && m1.tools[0].type === "tool" && m1.tools[0].status === "ok"
  && m1.tools[0].label === "视觉转译", "工具段挂在 spawn 上且带完成状态");
console.assert(m1.notes.length === 1 && m1.notes[0].includes("方法细节充分"), "工作说明挂在 spawn 上");
console.assert(m1.name === "深读评审员·m1", "同角色多实例消歧命名");
const m2 = room.spawns.find(s => s.key === "m2")!;
console.assert(m2.state === "failed", "失败 spawn 终态");
console.assert(room.tasks.done === 1 && room.tasks.failed === 1, "任务统计闭环");

const replay = reduceCollabChat(events);
console.assert(replay.spawns.length === room.spawns.length && replay.entries.length === room.entries.length, "重放幂等");
const mid = reduceCollabChat(events.slice(0, 8));
console.assert(mid.spawns.find(s => s.key === "m1")?.state === "running", "回放切片保持运行态");
console.assert(mid.spawns.find(s => s.key === "m1")?.tools.length === 1, "回放切片已见工具");
console.assert(digestMarkdown('{"a":1}').startsWith("```json"), "JSON digest 转代码块");
console.assert(digestMarkdown("普通结论") === "普通结论", "普通文本原样");

// —— 历史事件兼容：repair 与 score 是分开的实例（归并前的数据），前端按任务归并 ——
const legacy: CollabEvent[] = [
  ev("task_score:t9", { type: "instance.created" }, { agent_type: "task_scorer" }),
  ev("task_score:t9", { type: "task.started" }, { agent_type: "task_scorer" }),
  ev("evidence_repair:t9", { type: "instance.created" }, { agent_type: "task_scorer" }),
  ev("evidence_repair:t9", { type: "result.returned", receiver: "system", digest: "证据修正后评定 3 级", succeeded: true }, { agent_type: "task_scorer" }),
];
const legacyRoom = reduceCollabChat(legacy);
console.assert(legacyRoom.spawns.length === 1 && legacyRoom.spawns[0].key === "task_score:t9",
  "历史 repair 事件归并进评分实例");
console.assert(legacyRoom.spawns[0].state === "done" && legacyRoom.spawns[0].result?.text.includes("证据修正"),
  "归并后结论保留");

console.log("collab-chat smoke: all assertions passed");
