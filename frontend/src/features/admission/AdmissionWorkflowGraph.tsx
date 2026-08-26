import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import Icon from "@/components/ui/Icon";
import { IconButton } from "@/components/ui/Button";
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

interface GraphView {
  width: number;
  height: number;
  scale: number;
  offsetX: number;
  offsetY: number;
}

interface Point {
  x: number;
  y: number;
}

interface ScreenNode extends AdmissionGraphNode {
  screenX: number;
  screenY: number;
  screenRadius: number;
  labelWidth: number;
}

interface PointerState {
  pointerId: number;
  mode: "node" | "pan";
  nodeId?: string;
  startClientX: number;
  startClientY: number;
  originX: number;
  originY: number;
  originOffsetX: number;
  originOffsetY: number;
  moved: boolean;
}

function nodeLabelWidth(node: AdmissionGraphNode) {
  return node.kind === "task" || node.kind === "repair" ? 132 : 176;
}

function graphBounds(nodes: AdmissionGraphNode[], positions: Map<string, Point>) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  nodes.forEach((node) => {
    const point = positions.get(node.id) || node;
    const halfWidth = nodeLabelWidth(node) / 2;
    minX = Math.min(minX, point.x - halfWidth);
    maxX = Math.max(maxX, point.x + halfWidth);
    minY = Math.min(minY, point.y - node.radius - 12);
    maxY = Math.max(maxY, point.y + node.radius + 44);
  });
  if (!Number.isFinite(minX)) return { minX: 0, minY: 0, maxX: 1000, maxY: 640 };
  return { minX, minY, maxX, maxY };
}

export default function AdmissionWorkflowGraph({ run, candidate, jd, selectedNodeId, onSelectNode }: Props) {
  const { t } = useI18n();
  const nodes = useMemo(() => buildNodes(run, candidate, jd, t), [run, candidate, jd, t]);
  const wrapRef = useRef<HTMLDivElement>(null);
  const positionsRef = useRef(new Map<string, Point>());
  const pointerRef = useRef<PointerState | null>(null);
  const sizeRef = useRef({ width: 0, height: 0 });
  const viewRef = useRef<GraphView>({ width: 0, height: 0, scale: 1, offsetX: 0, offsetY: 0 });
  const fitViewRef = useRef<() => void>(() => {});
  const [, setLayoutTick] = useState(0);
  const [view, setView] = useState<GraphView>(viewRef.current);

  const commitView = useCallback((next: GraphView) => {
    viewRef.current = next;
    setView(next);
  }, []);

  const positionedNodes = nodes.map((node) => {
    const point = positionsRef.current.get(node.id) || node;
    return { ...node, x: point.x, y: point.y };
  });

  const fitView = useCallback(() => {
    const { width, height } = sizeRef.current;
    if (!width || !height || !positionedNodes.length) return;
    const bounds = graphBounds(positionedNodes, positionsRef.current);
    const bw = Math.max(1, bounds.maxX - bounds.minX);
    const bh = Math.max(1, bounds.maxY - bounds.minY);
    const padding = 32;
    const scale = Math.min(1.2, (width - padding * 2) / bw, (height - padding * 2) / bh);
    const safeScale = Math.min(1.2, scale);
    commitView({
      width,
      height,
      scale: safeScale,
      offsetX: (width - bw * safeScale) / 2 - bounds.minX * safeScale,
      offsetY: (height - bh * safeScale) / 2 - bounds.minY * safeScale,
    });
  }, [commitView, positionedNodes]);

  useEffect(() => {
    const next = new Map<string, Point>();
    nodes.forEach((node) => {
      next.set(node.id, positionsRef.current.get(node.id) || { x: node.x, y: node.y });
    });
    positionsRef.current = next;
    setLayoutTick((value) => value + 1);
    requestAnimationFrame(() => fitViewRef.current());
  }, [nodes]);

  useEffect(() => {
    fitViewRef.current = fitView;
  }, [fitView]);

  useEffect(() => {
    const element = wrapRef.current;
    if (!element) return;
    const resize = () => {
      const next = { width: element.clientWidth, height: element.clientHeight };
      sizeRef.current = next;
      viewRef.current = { ...viewRef.current, ...next };
      setView(viewRef.current);
      requestAnimationFrame(() => fitViewRef.current());
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (selectedNodeId && nodes.some((node) => node.id === selectedNodeId)) return;
    const active = [...nodes].reverse().find((node) => node.status === "running") || nodes[nodes.length - 1];
    if (active) onSelectNode(active);
  }, [nodes, onSelectNode, selectedNodeId]);

  const viewportWidth = view.width || 640;
  const viewportHeight = view.height || 680;
  const screenNodes = useMemo<ScreenNode[]>(() => positionedNodes.map((node) => {
    const screenRadius = Math.max(16, Math.min(30, node.radius * view.scale));
    return {
      ...node,
      screenX: node.x * view.scale + view.offsetX,
      screenY: node.y * view.scale + view.offsetY,
      screenRadius,
      labelWidth: Math.max(104, Math.min(nodeLabelWidth(node), nodeLabelWidth(node) * view.scale)),
    };
  }), [positionedNodes, view]);
  const edges = useMemo(() => buildEdges(screenNodes.map((node) => ({
    ...node,
    x: node.screenX,
    y: node.screenY,
    radius: node.screenRadius,
  }))), [screenNodes]);

  const zoomAt = (factor: number, clientX?: number, clientY?: number) => {
    const current = viewRef.current;
    const width = current.width || viewportWidth;
    const height = current.height || viewportHeight;
    const anchorX = clientX === undefined ? width / 2 : clientX;
    const anchorY = clientY === undefined ? height / 2 : clientY;
    const worldX = (anchorX - current.offsetX) / current.scale;
    const worldY = (anchorY - current.offsetY) / current.scale;
    const scale = Math.max(0.1, Math.min(2.6, current.scale * factor));
    commitView({
      width,
      height,
      scale,
      offsetX: anchorX - worldX * scale,
      offsetY: anchorY - worldY * scale,
    });
  };

  const beginPointer = (event: ReactPointerEvent<HTMLDivElement>, mode: "node" | "pan", nodeId?: string) => {
    event.preventDefault();
    event.stopPropagation();
    const node = nodeId ? positionsRef.current.get(nodeId) : undefined;
    const current = viewRef.current;
    pointerRef.current = {
      pointerId: event.pointerId,
      mode,
      nodeId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      originX: node?.x || 0,
      originY: node?.y || 0,
      originOffsetX: current.offsetX,
      originOffsetY: current.offsetY,
      moved: false,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };

  const movePointer = (event: ReactPointerEvent<HTMLDivElement>) => {
    const active = pointerRef.current;
    if (!active || active.pointerId !== event.pointerId) return;
    const dx = event.clientX - active.startClientX;
    const dy = event.clientY - active.startClientY;
    if (Math.abs(dx) + Math.abs(dy) > 4) active.moved = true;
    const current = viewRef.current;
    if (active.mode === "pan") {
      commitView({ ...current, offsetX: active.originOffsetX + dx, offsetY: active.originOffsetY + dy });
      return;
    }
    if (!active.nodeId) return;
    const node = positionsRef.current.get(active.nodeId);
    if (!node) return;
    const maxDrift = 140;
    const next = {
      x: Math.max(active.originX - maxDrift, Math.min(active.originX + maxDrift, active.originX + dx / Math.max(0.18, current.scale))),
      y: Math.max(active.originY - maxDrift, Math.min(active.originY + maxDrift, active.originY + dy / Math.max(0.18, current.scale))),
    };
    positionsRef.current.set(active.nodeId, next);
    setLayoutTick((value) => value + 1);
  };

  const endPointer = (event: ReactPointerEvent<HTMLDivElement>) => {
    const active = pointerRef.current;
    if (!active || active.pointerId !== event.pointerId) return;
    if (active.mode === "node" && active.nodeId && !active.moved) {
      const node = positionedNodes.find((item) => item.id === active.nodeId);
      if (node) onSelectNode(node);
    }
    pointerRef.current = null;
  };

  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void wrapRef.current?.requestFullscreen();
  };

  return (
    <div
      ref={wrapRef}
      className="admission-graph-canvas relative h-[clamp(620px,72vh,900px)] w-full min-w-0 touch-none select-none overflow-hidden"
      onPointerDown={(event) => beginPointer(event, "pan")}
      onPointerMove={movePointer}
      onPointerUp={endPointer}
      onPointerCancel={endPointer}
      onWheel={(event) => {
        event.preventDefault();
        const rect = wrapRef.current?.getBoundingClientRect();
        zoomAt(
          event.deltaY > 0 ? 0.9 : 1.1,
          rect ? event.clientX - rect.left : undefined,
          rect ? event.clientY - rect.top : undefined,
        );
      }}
    >
      <svg
        className="pointer-events-none absolute inset-0 h-full w-full"
        viewBox={`0 0 ${viewportWidth} ${viewportHeight}`}
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

      {screenNodes.map((node, index) => {
        const level = taskLevel(node.event);
        const selected = node.id === selectedNodeId;
        const showLabel = node.kind !== "task" && node.kind !== "repair"
          || view.scale >= 0.56
          || selected;
        return (
          <div
            key={node.id}
            className={cn(
              "admission-graph-node absolute flex flex-col items-center text-center cursor-grab active:cursor-grabbing",
              `is-${node.status}`,
              `kind-${node.kind}`,
              selected && "is-selected",
            )}
            style={{
              left: node.screenX,
              top: node.screenY - node.screenRadius,
              width: node.labelWidth,
              animationDelay: `${Math.min(index * 55, 330)}ms`,
            }}
            role="button"
            tabIndex={0}
            aria-label={`${node.label}，${node.summary}`}
            aria-current={selected ? "step" : undefined}
            onPointerDown={(event) => beginPointer(event, "node", node.id)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                onSelectNode(node);
              }
            }}
          >
            <span
              className="admission-node-orbit relative flex items-center justify-center rounded-full bg-surface-lowest"
              style={{ width: node.screenRadius * 2, height: node.screenRadius * 2 }}
            >
              {node.kind === "source" && !node.icon ? (
                <span className="font-medium" style={{ fontSize: Math.max(13, node.screenRadius * 0.68) }}>{(candidate?.name || t("候选人")).slice(0, 1)}</span>
              ) : level !== null ? (
                <span className="font-mono font-medium tabular-nums" style={{ fontSize: Math.max(12, node.screenRadius * 0.64) }}>{level}</span>
              ) : (
                <Icon name={node.icon || "circle"} size={Math.max(13, Math.min(20, node.screenRadius * 0.72))} />
              )}
              {node.status === "completed" && node.kind !== "source" && (
                <span className="admission-node-status-dot"><Icon name="check" size={9} /></span>
              )}
            </span>
            {showLabel && (
              <>
                <span className={cn("mt-2 block max-w-full truncate text-label", selected ? "text-on-surface" : "text-on-surface-variant")}>
                  {node.label}
                </span>
                {(node.kind === "source" || node.kind === "decision") && (
                  <span className="mt-0.5 block max-w-full truncate text-[10px] leading-4 text-on-surface-variant">
                    {node.summary}
                  </span>
                )}
              </>
            )}
            {!showLabel && (
              <span className="sr-only">{node.label}</span>
            )}
            {node.kind === "task" && selected && (
              <span className="sr-only">{node.summary}</span>
            )}
            {node.kind === "repair" && selected && (
              <span className="sr-only">{node.summary}</span>
            )}
          </div>
        );
      })}

      <div className="pointer-events-none absolute inset-x-3 bottom-3 flex items-end justify-between gap-3">
        <p className="rounded-sm bg-surface-lowest/90 px-2 py-1 text-[11px] text-on-surface-variant shadow-[var(--shadow-1)]">
          {t("节点可轻微拖动 · 滚轮缩放 · 空白处平移")}
        </p>
        <div
          className="pointer-events-auto flex items-center rounded-full border border-outline-variant bg-surface-lowest/95 shadow-[var(--shadow-1)]"
          onPointerDown={(event) => event.stopPropagation()}
        >
          <IconButton icon="remove" size={17} className="h-9 w-9" onClick={() => zoomAt(0.82)} title={t("缩小")} />
          <IconButton icon="add" size={17} className="h-9 w-9" onClick={() => zoomAt(1.22)} title={t("放大")} />
          <IconButton icon="center_focus_strong" size={17} className="h-9 w-9" onClick={() => fitViewRef.current()} title={t("定位")} />
          <IconButton icon="fullscreen" size={17} className="h-9 w-9" onClick={toggleFullscreen} title={t("全屏")} />
        </div>
      </div>
    </div>
  );
}
