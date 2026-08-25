import { useEffect, useMemo } from "react";
import Icon from "@/components/ui/Icon";
import type {
  CandidateBrief,
  InterviewAssessmentRun,
  JdEntry,
  WorkflowNodeEvent,
} from "@/lib/types";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

type NodeStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
type NodeKind = "source" | "phase" | "task" | "repair" | "decision";

export interface AdmissionGraphNode {
  id: string;
  label: string;
  summary: string;
  status: NodeStatus;
  kind: NodeKind;
  x: number;
  y: number;
  radius: number;
  icon?: string;
  parentIds: string[];
  event?: WorkflowNodeEvent;
}

interface GraphEdge {
  id: string;
  from: AdmissionGraphNode;
  to: AdmissionGraphNode;
  path: string;
  active: boolean;
}

interface Props {
  run: InterviewAssessmentRun;
  candidate?: CandidateBrief;
  jd?: JdEntry;
  selectedNodeId: string | null;
  onSelectNode: (node: AdmissionGraphNode) => void;
}

const PHASE_META: Record<string, { icon: string; kind: NodeKind }> = {
  input_preparation: { icon: "lock", kind: "phase" },
  capability_mapping: { icon: "account_tree", kind: "phase" },
  task_scoring: { icon: "target", kind: "phase" },
  evidence_validation: { icon: "fact_check", kind: "phase" },
  overall_review: { icon: "list_checks", kind: "phase" },
  admission_decision: { icon: "badge_check", kind: "decision" },
};

type Translate = ReturnType<typeof useI18n>["t"];

function normalizeStatus(status: string): NodeStatus {
  if (status === "completed" || status === "failed" || status === "cancelled" || status === "running") return status;
  return "queued";
}

function latestEvents(trace: WorkflowNodeEvent[]): WorkflowNodeEvent[] {
  const order: string[] = [];
  const latest = new Map<string, WorkflowNodeEvent>();
  trace.forEach((event) => {
    if (!latest.has(event.node_id)) order.push(event.node_id);
    latest.set(event.node_id, event);
  });
  return order.map((id) => latest.get(id)!).filter(Boolean);
}

function taskLevel(event?: WorkflowNodeEvent): number | null {
  const value = event?.detail?.level;
  return typeof value === "number" ? value : null;
}

function buildNodes(run: InterviewAssessmentRun, candidate: CandidateBrief | undefined, jd: JdEntry | undefined, t: Translate): AdmissionGraphNode[] {
  const events = latestEvents(run.run_trace || []);
  const byId = new Map(events.map((event) => [event.node_id, event]));
  const nodes: AdmissionGraphNode[] = [
    {
      id: "source:candidate",
      label: candidate?.name || t("候选人"),
      summary: candidate?.role || candidate?.stage || t("候选人简历"),
      status: "completed",
      kind: "source",
      x: 365,
      y: 62,
      radius: 24,
      parentIds: [],
    },
    {
      id: "source:jd",
      label: jd?.title || t("岗位 JD"),
      summary: jd?.assessment_card?.role_summary || jd?.team || t("岗位评估卡"),
      status: "completed",
      kind: "source",
      x: 635,
      y: 62,
      radius: 24,
      icon: "work",
      parentIds: [],
    },
  ];

  if (!events.length) {
    nodes.push({
      id: "queue",
      label: run.status === "queued" ? t("等待调度") : t("准备运行"),
      summary: t("正在等待可用评估槽位"),
      status: run.status === "failed" ? "failed" : "running",
      kind: "phase",
      x: 500,
      y: 178,
      radius: 21,
      icon: "hourglass_empty",
      parentIds: ["source:candidate", "source:jd"],
    });
    return nodes;
  }

  const phaseOrder = ["input_preparation", "capability_mapping", "task_scoring"];
  let y = 176;
  let previous = ["source:candidate", "source:jd"];
  phaseOrder.forEach((id) => {
    const event = byId.get(id);
    if (!event) return;
    const meta = PHASE_META[id];
    nodes.push({
      id,
      label: event.label ? t(event.label) : id,
      summary: t(event.summary),
      status: normalizeStatus(event.status),
      kind: meta.kind,
      x: 500,
      y,
      radius: 22,
      icon: meta.icon,
      parentIds: previous,
      event,
    });
    previous = [id];
    y += 112;
  });

  const taskEvents = events.filter((event) => event.node_id.startsWith("task_score:"));
  if (taskEvents.length) {
    const spread = Math.min(720, Math.max(260, taskEvents.length * 128));
    const start = 500 - spread / 2;
    const step = taskEvents.length === 1 ? 0 : spread / (taskEvents.length - 1);
    taskEvents.forEach((event, index) => {
      nodes.push({
        id: event.node_id,
        label: event.label ? t(event.label) : t("核心任务"),
        summary: t(event.summary),
        status: normalizeStatus(event.status),
        kind: "task",
        x: taskEvents.length === 1 ? 500 : start + step * index,
        y,
        radius: 19,
        parentIds: [byId.has("task_scoring") ? "task_scoring" : previous[0]],
        event,
      });
    });
    previous = taskEvents.map((event) => event.node_id);
    y += 126;
  }

  const evidenceEvent = byId.get("evidence_validation");
  if (evidenceEvent) {
    nodes.push({
      id: evidenceEvent.node_id,
      label: evidenceEvent.label ? t(evidenceEvent.label) : t("证据校验"),
      summary: t(evidenceEvent.summary),
      status: normalizeStatus(evidenceEvent.status),
      kind: "phase",
      x: 500,
      y,
      radius: 22,
      icon: PHASE_META.evidence_validation.icon,
      parentIds: previous,
      event: evidenceEvent,
    });
    previous = [evidenceEvent.node_id];
    y += 112;
  }

  const repairEvents = events.filter((event) => event.node_id.startsWith("evidence_repair:"));
  if (repairEvents.length) {
    const spread = Math.min(620, Math.max(220, repairEvents.length * 142));
    const start = 500 - spread / 2;
    const step = repairEvents.length === 1 ? 0 : spread / (repairEvents.length - 1);
    repairEvents.forEach((event, index) => {
      nodes.push({
        id: event.node_id,
        label: event.label ? t(event.label) : t("证据修正"),
        summary: t(event.summary),
        status: normalizeStatus(event.status),
        kind: "repair",
        x: repairEvents.length === 1 ? 500 : start + step * index,
        y,
        radius: 18,
        icon: "build",
        parentIds: [evidenceEvent ? evidenceEvent.node_id : previous[0]],
        event,
      });
    });
    previous = repairEvents.map((event) => event.node_id);
    y += 118;
  }

  ["overall_review", "admission_decision"].forEach((id) => {
    const event = byId.get(id);
    if (!event) return;
    const meta = PHASE_META[id];
    nodes.push({
      id,
      label: event.label ? t(event.label) : id,
      summary: t(event.summary),
      status: normalizeStatus(event.status),
      kind: meta.kind,
      x: 500,
      y,
      radius: id === "admission_decision" ? 27 : 22,
      icon: meta.icon,
      parentIds: previous,
      event,
    });
    previous = [id];
    y += id === "admission_decision" ? 92 : 118;
  });

  return nodes;
}

function edgePath(from: AdmissionGraphNode, to: AdmissionGraphNode): string {
  const startY = from.y + from.radius + 8;
  const endY = to.y - to.radius - 8;
  const controlY = startY + (endY - startY) * 0.52;
  return `M ${from.x} ${startY} C ${from.x} ${controlY}, ${to.x} ${controlY}, ${to.x} ${endY}`;
}

function buildEdges(nodes: AdmissionGraphNode[]): GraphEdge[] {
  const map = new Map(nodes.map((node) => [node.id, node]));
  return nodes.flatMap((node) => node.parentIds.flatMap((parentId) => {
    const parent = map.get(parentId);
    if (!parent) return [];
    return [{
      id: `${parent.id}->${node.id}`,
      from: parent,
      to: node,
      path: edgePath(parent, node),
      active: node.status === "running",
    }];
  }));
}

export default function AdmissionWorkflowGraph({ run, candidate, jd, selectedNodeId, onSelectNode }: Props) {
  const { t } = useI18n();
  const nodes = useMemo(() => buildNodes(run, candidate, jd, t), [run, candidate, jd, t]);
  const edges = useMemo(() => buildEdges(nodes), [nodes]);
  const height = Math.max(520, Math.max(...nodes.map((node) => node.y)) + 108);

  useEffect(() => {
    if (selectedNodeId && nodes.some((node) => node.id === selectedNodeId)) return;
    const active = [...nodes].reverse().find((node) => node.status === "running") || nodes[nodes.length - 1];
    if (active) onSelectNode(active);
  }, [nodes, onSelectNode, selectedNodeId]);

  return (
    <div className="admission-graph-canvas relative min-w-[620px]" style={{ height }}>
      <svg
        className="absolute inset-0 h-full w-full overflow-visible"
        viewBox={`0 0 1000 ${height}`}
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        {edges.map((edge) => (
          <g key={edge.id}>
            <path
              d={edge.path}
              pathLength={1}
              className="admission-graph-edge"
            />
            {edge.active && (
              <path
                d={edge.path}
                pathLength={1}
                className="admission-graph-edge-flow"
              />
            )}
          </g>
        ))}
      </svg>

      {nodes.map((node, index) => {
        const level = taskLevel(node.event);
        const selected = node.id === selectedNodeId;
        return (
          <button
            key={node.id}
            type="button"
            onClick={() => onSelectNode(node)}
            aria-label={`${node.label}，${node.summary}`}
            aria-current={selected ? "step" : undefined}
            className={cn(
              "admission-graph-node absolute flex flex-col items-center text-center cursor-pointer",
              `is-${node.status}`,
              `kind-${node.kind}`,
              selected && "is-selected",
            )}
            style={{
              left: `${node.x / 10}%`,
              top: node.y,
              width: node.kind === "task" || node.kind === "repair" ? 132 : 176,
              marginLeft: node.kind === "task" || node.kind === "repair" ? -66 : -88,
              animationDelay: `${Math.min(index * 55, 330)}ms`,
            }}
          >
            <span
              className="admission-node-orbit relative flex items-center justify-center rounded-full bg-surface-lowest"
              style={{ width: node.radius * 2, height: node.radius * 2 }}
            >
              {node.kind === "source" && !node.icon ? (
                <span className="text-title">{(candidate?.name || t("候选人")).slice(0, 1)}</span>
              ) : level !== null ? (
                <span className="font-mono text-title tabular-nums">{level}</span>
              ) : (
                <Icon name={node.icon || "circle"} size={node.kind === "decision" ? 20 : 17} />
              )}
              {node.status === "completed" && node.kind !== "source" && (
                <span className="admission-node-status-dot"><Icon name="check" size={9} /></span>
              )}
            </span>
            <span className={cn("mt-2 block max-w-full truncate text-label", selected ? "text-on-surface" : "text-on-surface-variant")}>
              {node.label}
            </span>
            {(node.kind === "source" || node.kind === "decision") && (
              <span className="mt-0.5 block max-w-full truncate text-[10px] leading-4 text-on-surface-variant">
                {node.summary}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
