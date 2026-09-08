// 归约器冒烟验证：续派同实例、幂等重放、定位恢复、增量折叠（node --import tsx scripts/verify-collab-scene.mts）
import { reduceCollabEvents, instanceName } from "../src/features/admission/collabSceneModel";
import type { CollabEvent } from "../src/lib/types";

let seq = -1;
const ev = (instance_id: string | null, event: Record<string, unknown>, extra: Partial<CollabEvent> = {}): CollabEvent => ({
  protocol: "agent-collab/v1", run_id: "r1", run_kind: "panel", event_id: `e${++seq}`, seq,
  at: null, instance_id, agent_type: null, task_id: null, task_kind: null, turn_no: null,
  message_id: null, cause_event_id: null, event: { type: "", ...event }, ...extra,
});

const events: CollabEvent[] = [
  ev("chair", { type: "run.started" }),
  ev("chair", { type: "planning.started", round_no: 1 }, { agent_type: "chair" }),
  ev("m1", { type: "instance.created" }, { agent_type: "verify" }),
  ev("chair", { type: "task.dispatched", sender: "chair", receiver: "m1", instruction: "核实贡献", reuse_context: false }, { agent_type: "chair", task_id: "m1", turn_no: 1, message_id: "msg1" }),
  ev("m1", { type: "task.started" }, { agent_type: "verify", task_id: "m1", turn_no: 1 }),
  ev("m1", { type: "tool.started", call_id: "c1", tool: "read_pages", args_summary: "项目说明.pdf" }, { agent_type: "verify" }),
  ev("m1", { type: "tool.completed", call_id: "c1", tool: "read_pages", status: "ok", summary: "找到说明" }, { agent_type: "verify" }),
  ev("m1", { type: "message.completed", sender: "m1", receiver: "chair", text: "## 发现\n正文" }, { agent_type: "verify" }),
  ev("m1", { type: "task.completed" }, { agent_type: "verify", task_id: "m1", turn_no: 1 }),
  ev("m1", { type: "result.returned", sender: "m1", receiver: "chair", digest: "已确认贡献", succeeded: true, artifact_id: "findings:m1", reply_to: "msg1" }, { agent_type: "verify", task_id: "m1", turn_no: 1, message_id: "msg2" }),
  ev("chair", { type: "task.dispatched", sender: "chair", receiver: "m1", instruction: "边界复核", note: "沿用上下文", reuse_context: true }, { agent_type: "chair", task_id: "m1", turn_no: 2, message_id: "msg3" }),
  ev("m1", { type: "task.started" }, { agent_type: "verify", task_id: "m1", turn_no: 2 }),
  ev("m1", { type: "task.failed", error: "读取超时" }, { agent_type: "verify", task_id: "m1", turn_no: 2 }),
  ev("chair", { type: "run.completed" }, { agent_type: "chair" }),
];

const scene = reduceCollabEvents(events);
const m1 = scene.instances.get("m1")!;
const chair = scene.instances.get("chair")!;

console.assert(scene.instances.size === 2, "实例数应为 2（chair+m1）");
console.assert(m1.turn === 2, "续派后轮次应为 2");
console.assert(m1.state === "failed", "失败终态");
console.assert(chair.state === "reviewing", "主席收到回传后进入审阅，实际 " + chair.state);
console.assert(scene.exchanges.length === 3 && scene.exchanges[1].kind === "result", "三次交接（两轮派工+一次回传）");
console.assert(scene.exchanges[1].replyTo === "msg1", "回传回复首轮派工消息");
console.assert(scene.messages.length === 1 && scene.tools.size === 1, "消息与工具记录");
console.assert(instanceName(m1) === "证据查证评审员", "角色名映射");

const replay = reduceCollabEvents(events);
console.assert(replay.exchanges.length === 3 && replay.instances.size === 2, "重放幂等");
const mid = reduceCollabEvents(events.slice(0, 5));
console.assert(mid.instances.get("m1")!.state === "working", "定位恢复工作态，实际 " + mid.instances.get("m1")!.state);
console.assert(mid.exchanges.length === 1, "定位时只保留已发生交接");
const grown = reduceCollabEvents(events.slice(6), reduceCollabEvents(events.slice(0, 6)));
console.assert(grown.exchanges.length === 3 && grown.instances.get("m1")!.state === "failed", "增量折叠与全量一致");
console.log("scene-model smoke: all assertions passed");
