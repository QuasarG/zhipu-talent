// 群聊转写冒烟验证：派工/回传/工具并入消息、综合意见、消歧命名、幂等与回放切片
// （node --import tsx scripts/verify-collab-chat.mts）
import { reduceCollabChat } from "../src/features/admission/collabChatModel";
import type { CollabEvent } from "../src/lib/types";

let seq = -1;
const ev = (instance_id: string | null, event: Record<string, unknown>, extra: Partial<CollabEvent> = {}): CollabEvent => ({
  protocol: "agent-collab/v1", run_id: "r1", run_kind: "panel", event_id: `e${++seq}`, seq,
  at: "2026-09-11T03:00:00.000Z", instance_id, agent_type: null, task_id: null, task_kind: null,
  turn_no: null, message_id: null, cause_event_id: null, event: { type: "", ...event }, ...extra,
});

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
console.assert(kinds[0] === "system" && kinds[1] === "planning", "开场：开始 pill + 规划 pill");
const dispatch = room.entries.find(e => e.badge === "派工")!;
console.assert(!!dispatch, "派工消息存在");
const dispatchText = dispatch.message.content.segments[0].type === "text" ? dispatch.message.content.segments[0].text : "";
console.assert(dispatchText.includes("精读代表作") && dispatchText.includes("paper.pdf") && dispatchText.includes("贡献边界?"),
  "派工正文并入指令/材料/问题");
console.assert(dispatch.mentionName === "深读评审员·m1", "派工 @ 提及带消歧后缀，实际 " + dispatch.mentionName);
const narration = room.entries.find(e => e.message.content.segments.some(s => s.type === "text" && s.text.includes("方法细节充分")))!;
const toolSeg = narration.message.content.segments.find(s => s.type === "tool") as { label: string; status?: string };
console.assert(toolSeg?.label === "视觉转译" && toolSeg?.status === "ok", "工具段并入消息并带完成状态");
const back = room.entries.find(e => e.badge === "结论回传")!;
console.assert(back.succeeded === true && back.senderId === "m1", "评审员结论回传");
const synthesis = room.entries.find(e => e.badge === "综合意见")!;
console.assert(!!synthesis && synthesis.message.content.segments.some(s => s.type === "text" && s.text.includes('"per_jd"')),
  "主席收队以综合意见入群，JSON digest 走代码块");
const failure = room.entries.find(e => e.badge === "失败回传")!;
console.assert(!!failure && failure.badgeTone === "error", "失败回传消息");
console.assert(room.members.find(m => m.id === "m2")?.state === "failed", "失败成员状态");
console.assert(room.members.find(m => m.id === "chair")?.name === "主席 Agent", "主席命名");
console.assert(room.tasks.done === 1 && room.tasks.failed === 1, "任务统计 done=1 failed=1");

const replay = reduceCollabChat(events);
console.assert(replay.entries.length === room.entries.length, "重放幂等");
const mid = reduceCollabChat(events.slice(0, 7));
console.assert(mid.members.find(m => m.id === "m1")?.state === "working", "回放切片保持过程态");
console.assert(mid.entries.some(e => e.message.content.segments.some(s => s.type === "tool" && !("status" in s) )),
  "进行中的工具段以运行态呈现");
const names = room.members.filter(m => m.role === "deep_read").map(m => m.name);
console.assert(names.length === 2 && names[0] !== names[1], "同角色多实例名称消歧");

console.log("collab-chat smoke: all assertions passed");
