import type { PanelTraceEvent, WorkflowNodeEvent } from "@/lib/types";

export interface Activity {
  id: string; agent: string; role: string; target?: string; kind: string; status: string;
  text: string; at?: string | null; detail?: Record<string, unknown>; mission?: string | null; goal?: string | null;
}
export const kinds: Record<string, string> = { dispatch: "派工", handoff: "回传 / 交接", request: "开始工作",
  message: "工作说明", tool_call: "调用工具", tool_result: "工具返回", error: "执行失败", status: "进度", legacy: "历史记录" };
export const roleNames: Record<string, string> = {
  chair: "主席 Agent", verify: "证据查证评审员", deep_read: "深读评审员",
  jd_match: "岗位对照评审员", cross_check: "仲裁评审员", generic: "通用评审员",
  mapper: "能力映射 Agent", task_scorer: "任务评分 Agent", reviewer: "评分总审 Agent",
  system: "系统", evaluator: "评估 Agent", observer: "督导 Agent",
};
export function panelActivities(trace: PanelTraceEvent[]): Activity[] {
  return trace.map((e, i) => ({
    id: `${i}`, agent: e.agent_id || (e.mission_id || (e.node === "panel_lead" ? "chair" : "system")),
    role: e.agent_type || (e.mission_type || (e.node === "panel_lead" ? "chair" : "system")),
    target: e.target_id, kind: e.event_kind || "legacy", status: e.mission_status || e.status,
    text: e.message, at: e.ts, detail: e.detail, mission: e.agent_id === "chair" ? null : e.mission_id,
    goal: e.agent_id === "chair" ? null : e.mission_goal,
  }));
}
export function admissionActivities(trace: WorkflowNodeEvent[]): Activity[] {
  return trace.map((e, i) => {
    const role = e.agent_type || (e.node_id.startsWith("task_score:") || e.node_id.startsWith("evidence_repair:")
      ? "task_scorer" : e.node_id === "capability_mapping" ? "mapper"
        : e.node_id === "overall_review" ? "reviewer" : "system");
    return { id: `${i}`, agent: e.agent_id || (role === "system" ? "system" : e.node_id),
      role, target: e.target_id, kind: e.event_kind || "legacy", status: e.status,
      text: e.summary, at: e.at, detail: e.detail, goal: e.label,
      mission: role === "task_scorer" ? e.node_id : null };
  });
}
export function activeAgents(events: Activity[], running: boolean): Activity[] {
  if (!running) return [];
  const latest = new Map<string, Activity>();
  for (const e of events) {
    latest.set(e.agent, e);
    if (e.kind === "dispatch" || e.kind === "handoff") latest.delete(e.agent);
  }
  const current = [...latest.values()].filter(e => e.status === "running" && e.kind !== "legacy");
  return current.some(e => e.role !== "system") ? current.filter(e => e.role !== "system") : current;
}
