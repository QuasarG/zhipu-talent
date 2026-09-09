// agent-collab/v1 场景归约：纯函数把协作事件流折叠为工位状态。
// 实时与回放共用同一解释逻辑；重复事件按 event_id 幂等跳过，续派不新建实例。
import type { CollabEvent } from "@/lib/types";
import { roleNames } from "./agentActivityModel";

export type InstanceState = "waiting" | "working" | "reviewing" | "done" | "failed";
export type ActionKind = "planning" | "reading" | "searching" | "analyzing" | "tool" | "messaging" | null;

export interface SceneInstance {
  id: string;
  role: string;
  state: InstanceState;
  turn: number;
  taskGoal: string;
  note: string;
  action: string | null;
  actionKind: ActionKind;
  bornSeq: number;
  lastSeq: number;
}

export interface SceneTask {
  key: string;
  instanceId: string;
  taskId: string;
  turn: number;
  goal: string;
  state: "dispatched" | "started" | "completed" | "failed";
}

export interface SceneExchange {
  eventId: string;
  seq: number;
  at: string | null;
  sender: string;
  receiver: string;
  kind: "dispatch" | "result";
  text: string;
  artifactId?: string;
  succeeded: boolean;
  replyTo?: string | null;
  messageId?: string | null;
}

export interface SceneMessage {
  eventId: string;
  seq: number;
  sender: string;
  receiver: string;
  text: string;
  at: string | null;
}

export interface SceneTool {
  eventId: string;
  seq: number;
  callId: string;
  instanceId: string;
  tool: string;
  argsSummary: string;
  status: "running" | "ok" | "error";
  summary: string;
  at: string | null;
}

export interface CollabScene {
  runState: "starting" | "running" | "completed" | "failed" | "cancelled";
  instances: Map<string, SceneInstance>;
  tasks: Map<string, SceneTask>;
  exchanges: SceneExchange[];
  messages: SceneMessage[];
  tools: Map<string, SceneTool>;
  applied: Set<string>;
  lastSeq: number;
}

export const emptyScene = (): CollabScene => ({
  runState: "starting",
  instances: new Map(),
  tasks: new Map(),
  exchanges: [],
  messages: [],
  tools: new Map(),
  applied: new Set(),
  lastSeq: -1,
});

const toolAction = (tool: string): ActionKind =>
  tool.startsWith("read") || tool === "list_files" ? "reading"
    : tool.includes("search") || tool === "verify_paper" || tool === "web_search" ? "searching"
      : tool ? "tool" : null;

const textOf = (value: unknown): string =>
  typeof value === "string" ? value : value === undefined || value === null ? "" : JSON.stringify(value);

export const instanceName = (instance: SceneInstance): string =>
  roleNames[instance.role] || instance.id;

function ensureInstance(scene: CollabScene, id: string, role: string, seq: number): SceneInstance {
  let instance = scene.instances.get(id);
  if (!instance) {
    instance = { id, role, state: "waiting", turn: 1, taskGoal: "", note: "", action: null, actionKind: null, bornSeq: seq, lastSeq: seq };
    scene.instances.set(id, instance);
  }
  instance.lastSeq = seq;
  return instance;
}

/** 折叠事件（可增量：传入 base 场景与新增事件）。重复 event_id 直接跳过。 */
export function reduceCollabEvents(events: CollabEvent[], base?: CollabScene): CollabScene {
  const scene: CollabScene = base ? {
    runState: base.runState,
    instances: new Map([...base.instances].map(([k, v]) => [k, { ...v }])),
    tasks: new Map([...base.tasks].map(([k, v]) => [k, { ...v }])),
    exchanges: [...base.exchanges],
    messages: [...base.messages],
    tools: new Map([...base.tools].map(([k, v]) => [k, { ...v }])),
    applied: new Set(base.applied),
    lastSeq: base.lastSeq,
  } : emptyScene();

  for (const envelope of events) {
    if (scene.applied.has(envelope.event_id)) continue;
    scene.applied.add(envelope.event_id);
    if (envelope.seq > scene.lastSeq) scene.lastSeq = envelope.seq;

    const { event, instance_id: instanceId, agent_type: agentType } = envelope;
    const seq = envelope.seq;
    switch (event.type) {
      case "run.started":
        scene.runState = "running";
        break;
      case "run.completed":
        scene.runState = "completed";
        break;
      case "run.failed":
        scene.runState = "failed";
        break;
      case "run.cancelled":
        scene.runState = "cancelled";
        break;
      case "instance.created": {
        ensureInstance(scene, instanceId || "", agentType || event.agent_type || "", seq);
        break;
      }
      case "planning.started": {
        const chair = ensureInstance(scene, instanceId || "chair", "chair", seq);
        chair.state = "working";
        chair.actionKind = "planning";
        chair.action = `第 ${event.round_no ?? 1} 轮规划`;
        break;
      }
      case "planning.completed": {
        const chair = scene.instances.get(instanceId || "chair");
        if (chair && chair.state === "working" && chair.actionKind === "planning") {
          chair.state = "waiting";
          chair.actionKind = null;
          chair.action = null;
        }
        break;
      }
      case "task.dispatched": {
        const sender = ensureInstance(scene, instanceId || event.sender || "chair", agentType || "chair", seq);
        sender.lastSeq = seq;
        const targetId = event.receiver || "";
        const target = scene.instances.get(targetId) || ensureInstance(scene, targetId, "", seq);
        target.turn = envelope.turn_no || target.turn + 1;
        target.taskGoal = textOf(event.instruction);
        target.note = textOf(event.note);
        target.state = target.state === "done" || target.state === "failed" ? "waiting" : target.state;
        target.action = null;
        target.actionKind = null;
        const key = `${targetId}:${envelope.task_id || targetId}:${target.turn}`;
        scene.tasks.set(key, {
          key, instanceId: targetId, taskId: envelope.task_id || targetId,
          turn: target.turn, goal: textOf(event.instruction), state: "dispatched",
        });
        scene.exchanges.push({
          eventId: envelope.event_id, seq, at: envelope.at,
          sender: instanceId || "", receiver: targetId, kind: "dispatch",
          text: textOf(event.instruction) || textOf(event.note),
          succeeded: true, messageId: envelope.message_id || null, replyTo: null,
        });
        break;
      }
      case "task.started": {
        const instance = ensureInstance(scene, instanceId || "", agentType || "", seq);
        instance.state = "working";
        instance.action = null;
        instance.actionKind = null;
        const task = [...scene.tasks.values()].reverse()
          .find(t => t.instanceId === instance.id && t.state === "dispatched");
        if (task) task.state = "started";
        break;
      }
      case "message.started":
      case "message.completed": {
        const instance = scene.instances.get(instanceId || "");
        if (instance) {
          instance.state = instance.state === "done" || instance.state === "failed" ? instance.state : "working";
          instance.actionKind = "messaging";
          instance.action = textOf(event.text).slice(0, 80);
        }
        if (event.type === "message.completed" && event.text) {
          scene.messages.push({
            eventId: envelope.event_id, seq, sender: instanceId || "",
            receiver: event.receiver || "", text: textOf(event.text), at: envelope.at,
          });
        }
        break;
      }
      case "tool.started": {
        const instance = scene.instances.get(instanceId || "");
        const callId = textOf(event.call_id);
        if (instance) {
          instance.state = instance.state === "done" || instance.state === "failed" ? instance.state : "working";
          instance.actionKind = toolAction(textOf(event.tool));
          instance.action = textOf(event.args_summary);
        }
        if (callId) scene.tools.set(callId, {
          eventId: envelope.event_id, seq, callId, instanceId: instanceId || "",
          tool: textOf(event.tool), argsSummary: textOf(event.args_summary),
          status: "running", summary: "", at: envelope.at,
        });
        break;
      }
      case "tool.completed": {
        const instance = scene.instances.get(instanceId || "");
        const callId = textOf(event.call_id);
        const tool = scene.tools.get(callId);
        if (tool) {
          tool.status = event.status === "error" ? "error" : "ok";
          tool.summary = textOf(event.summary);
        }
        if (instance) instance.action = textOf(event.summary) || instance.action;
        break;
      }
      case "result.returned": {
        const sender = scene.instances.get(instanceId || event.sender || "");
        if (sender && sender.state !== "failed") sender.state = "done";
        const receiver = scene.instances.get(event.receiver || "");
        if (receiver && receiver.id !== sender?.id) {
          receiver.state = "reviewing";
          receiver.actionKind = "analyzing";
          receiver.action = textOf(event.digest).slice(0, 80);
        }
        // 回传即任务收尾：链路可能只发 result.returned 而没有独立 task.completed
        const settled = [...scene.tasks.values()].reverse()
          .find(t => t.instanceId === (instanceId || event.sender || "") && t.state !== "completed" && t.state !== "failed");
        if (settled) settled.state = event.succeeded === false ? "failed" : "completed";
        scene.exchanges.push({
          eventId: envelope.event_id, seq, at: envelope.at,
          sender: instanceId || event.sender || "", receiver: event.receiver || "",
          kind: "result", text: textOf(event.digest), artifactId: event.artifact_id,
          succeeded: event.succeeded !== false, messageId: envelope.message_id || null,
          replyTo: event.reply_to || null,
        });
        break;
      }
      case "task.completed": {
        const instance = scene.instances.get(instanceId || "");
        if (instance) { instance.state = "done"; instance.actionKind = null; }
        const task = [...scene.tasks.values()].reverse()
          .find(t => t.instanceId === (instanceId || "") && t.state !== "completed" && t.state !== "failed");
        if (task) task.state = "completed";
        break;
      }
      case "task.failed": {
        const instance = scene.instances.get(instanceId || "");
        if (instance) { instance.state = "failed"; instance.action = textOf(event.error).slice(0, 80); instance.actionKind = null; }
        const task = [...scene.tasks.values()].reverse()
          .find(t => t.instanceId === (instanceId || "") && t.state !== "completed" && t.state !== "failed");
        if (task) task.state = "failed";
        break;
      }
      default:
        break;
    }
  }
  return scene;
}
