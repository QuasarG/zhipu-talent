import { useEffect, useMemo } from "react";
import type {
  Evaluation,
  AcademicReport,
  EvaluationGraph,
  EvaluationGraphGroup,
  EvaluationGraphPhase,
  EvaluationNodeRun,
  EvaluationNodeStatus,
  EvaluationRun,
} from "@/lib/types";
import { useSessionState } from "@/lib/sessionState";
import Tabs from "@/components/ui/Tabs";
import Icon from "@/components/ui/Icon";
import { StatusChip } from "@/components/ui/Chip";
import ScoreOverview from "./ScoreOverview";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

interface Props {
  candidateId?: string;
  candidateName?: string;
  evaluation?: Evaluation;
  evaluationRun?: EvaluationRun;
  academicReport?: AcademicReport;
  graph: EvaluationGraph;
  liveNodeRuns: EvaluationNodeRun[];
  evaluating: boolean;
}

type EvaluationTab = "result" | "process";

export default function EvaluationWorkspace({ candidateName, candidateId = "none", evaluation, evaluationRun, academicReport, graph, liveNodeRuns, evaluating }: Props) {
  const statePrefix = `resume-evaluate.${candidateId}`;
  const [tab, setTab] = useSessionState<EvaluationTab>(`${statePrefix}.evaluation-tab`, evaluation ? "result" : "process");

  useEffect(() => {
    if (evaluating) setTab("process");
  }, [evaluating, setTab]);

  const completedCount = useMemo(() => {
    // 只统计图谱里展示出来的节点，后端 run 记录可能含已下线的历史节点（如 academic_check）
    const known = new Set(graph.phases.flatMap((phase) => phase.groups.flatMap((group) => group.nodes.map((node) => node.node))));
    const runs = mergeRuns(evaluationRun?.node_runs || evaluation?.node_runs || [], liveNodeRuns);
    return runs.filter((run) => known.has(run.node) && (run.status === "done" || run.status === "skipped")).length;
  }, [graph, evaluation?.node_runs, evaluationRun?.node_runs, liveNodeRuns]);

  const { t } = useI18n();

  return (
    <div className="flex flex-col h-full min-h-0">
      <Tabs
        className="shrink-0"
        items={[
          { value: "result", label: t("评估结果") },
          { value: "process", label: t("运行过程"), badge: evaluating ? t("运行中") : completedCount || undefined },
        ]}
        value={tab}
        onChange={setTab}
      />
      <div className="flex-1 min-h-0 overflow-y-auto pt-4 pr-1">
        {tab === "result" ? (
          evaluation ? <ScoreOverview evaluation={evaluation} academicReport={academicReport} candidateName={candidateName} /> : <ResultEmpty evaluating={evaluating} />
        ) : (
          <EvaluationProcess
            graph={graph}
            statePrefix={statePrefix}
            persistedRuns={evaluationRun?.node_runs || evaluation?.node_runs || []}
            liveRuns={liveNodeRuns}
            evaluating={evaluating}
          />
        )}
      </div>
    </div>
  );
}

function ResultEmpty({ evaluating }: { evaluating: boolean }) {
  const { t } = useI18n();
  return (
    <div className="flex flex-col items-center justify-center min-h-[360px] text-center gap-2">
      <Icon name={evaluating ? "pending_actions" : "fact_check"} size={40} className="text-on-surface-variant" />
      <p className="text-title font-bold">{evaluating ? t("评估正在运行") : t("尚无评估结果")}</p>
      <p className="text-body-sm text-on-surface-variant">
        {evaluating ? t("可在运行过程页查看当前节点") : t("完成论文核验后可启动评估")}
      </p>
    </div>
  );
}

function EvaluationProcess({ graph, statePrefix, persistedRuns, liveRuns, evaluating }: {
  graph: EvaluationGraph;
  statePrefix: string;
  persistedRuns: EvaluationNodeRun[];
  liveRuns: EvaluationNodeRun[];
  evaluating: boolean;
}) {
  const runMap = useMemo(() => {
    const merged = mergeRuns(persistedRuns, liveRuns);
    return new Map(merged.map((run) => [run.node, run]));
  }, [persistedRuns, liveRuns]);
  const { t } = useI18n();
  const phaseStatuses = deriveStatuses(graph, runMap, evaluating);
  const allStatuses = [...phaseStatuses.values()].flatMap((phase) => [...phase.values()]);
  const finished = allStatuses.filter((item) => item.status === "done" || item.status === "skipped").length;
  const failed = allStatuses.filter((item) => item.status === "error").length;
  const total = allStatuses.length;

  return (
    <div>
      <header className="pb-4 border-b-2 border-outline-variant">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-title-lg font-bold text-on-surface">{t("评估执行图谱")}</h2>
            <p className="mt-1 text-body-sm text-on-surface-variant">{t("完整展示节点、并行 Track 与实时运行状态")}</p>
          </div>
          <StatusChip
            tone={failed ? "error" : evaluating ? "primary" : finished === total && total ? "success" : "neutral"}
            variant={evaluating || failed ? "filled" : "dot"}
            icon={failed ? "error" : evaluating ? "sync" : finished === total && total ? "check_circle" : "schedule"}
          >
            {failed ? t("{n} 个失败", { n: failed }) : evaluating ? t("运行中") : finished === total && total ? t("已完成") : t("待运行")}
          </StatusChip>
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 mt-4">
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-high">
            <div
              className="h-full rounded-full bg-primary transition-[width] duration-500 ease-emphasized"
              style={{ width: total ? `${(finished / total) * 100}%` : "0%" }}
            />
          </div>
          <span className="text-label font-bold tabular-nums text-on-surface-variant">{finished} / {total}</span>
        </div>
      </header>

      <div className="divide-y-2 divide-outline-variant">
        {graph.phases.map((phase, index) => (
          <PhaseBlock
            key={phase.key}
            phase={phase}
            index={index}
            statuses={phaseStatuses.get(phase.key) || new Map()}
            statePrefix={statePrefix}
          />
        ))}
      </div>
    </div>
  );
}

interface DerivedStatus {
  status: EvaluationNodeStatus;
  message: string;
}

function deriveStatuses(graph: EvaluationGraph, runMap: Map<string, EvaluationNodeRun>, evaluating: boolean) {
  const result = new Map<string, Map<string, DerivedStatus>>();
  let activePhase = -1;

  if (evaluating) {
    activePhase = graph.phases.findIndex((phase) =>
      phase.groups.some((group) => group.nodes.some((node) => !isTerminal(runMap.get(node.node)?.status)))
    );
  }

  graph.phases.forEach((phase, phaseIndex) => {
    const nodeStatuses = new Map<string, DerivedStatus>();
    const pendingNodes = phase.groups.flatMap((group) => group.nodes).filter((node) => !isTerminal(runMap.get(node.node)?.status));
    const firstPending = pendingNodes[0]?.node;

    phase.groups.forEach((group) => group.nodes.forEach((node) => {
      const run = runMap.get(node.node);
      let status = run?.status || "pending";
      if (!run && evaluating && phaseIndex === activePhase) {
        status = phase.key === "parallel" || node.node === firstPending ? "running" : "pending";
      }
      nodeStatuses.set(node.node, { status, message: run?.message || node.description });
    }));
    result.set(phase.key, nodeStatuses);
  });
  return result;
}

function isTerminal(status?: EvaluationNodeStatus) {
  return status === "done" || status === "skipped" || status === "error";
}

function mergeRuns(persistedRuns: EvaluationNodeRun[], liveRuns: EvaluationNodeRun[]) {
  const merged = new Map<string, EvaluationNodeRun>();
  [...persistedRuns, ...liveRuns].forEach((run) => merged.set(run.node, run));
  return [...merged.values()];
}

function PhaseBlock({ phase, index, statuses, statePrefix }: {
  phase: EvaluationGraphPhase;
  index: number;
  statuses: Map<string, DerivedStatus>;
  statePrefix: string;
}) {
  const items = [...statuses.values()];
  const running = items.some((item) => item.status === "running");
  const failed = items.some((item) => item.status === "error");
  const complete = items.length > 0 && items.every((item) => isTerminal(item.status));
  const [open, setOpen] = useSessionState<boolean>(
    `${statePrefix}.phase-open.${phase.key}`,
    running || !complete,
  );

  useEffect(() => {
    if (running) setOpen(true);
  }, [running, setOpen]);

  return (
    <section className="py-1">
      <button
        type="button"
        className="state-layer grid grid-cols-[36px_minmax(0,1fr)_auto_24px] items-center gap-3 w-full px-2 py-3 text-left rounded-sm"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className={cn(
          "flex items-center justify-center w-8 h-8 rounded-sm text-label font-bold tabular-nums",
          failed ? "bg-error-container text-error" : running ? "bg-primary-container text-primary" : complete ? "bg-success-container text-success" : "bg-surface-high text-on-surface-variant",
        )}>
          {String(index + 1).padStart(2, "0")}
        </span>
        <span className="min-w-0">
          <span className="block text-title font-bold text-on-surface">{phase.label}</span>
          <span className="block mt-0.5 text-label text-on-surface-variant truncate">{phase.description}</span>
        </span>
        <PhaseState running={running} failed={failed} complete={complete} />
        <Icon name="expand_more" size={20} className={cn("text-on-surface-variant transition-transform duration-300 ease-emphasized", open && "rotate-180")} />
      </button>
      <div className="process-collapse" data-open={open}>
        <div>
          <div className="ml-[54px] pb-3 border-l-2 border-outline-variant">
            {phase.groups.map((group) => (
              <NodeGroup key={group.key} group={group} statuses={statuses} statePrefix={statePrefix} />
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function PhaseState({ running, failed, complete }: { running: boolean; failed: boolean; complete: boolean }) {
  const { t } = useI18n();
  if (failed) return <span className="text-label font-bold text-error">{t("失败")}</span>;
  if (running) return <span className="text-label font-bold text-primary">{t("运行中")}</span>;
  if (complete) return <span className="text-label font-bold text-success">{t("已完成")}</span>;
  return <span className="text-label font-medium text-on-surface-variant">{t("待运行")}</span>;
}

function NodeGroup({ group, statuses, statePrefix }: { group: EvaluationGraphGroup; statuses: Map<string, DerivedStatus>; statePrefix: string }) {
  const active = group.nodes.some((node) => statuses.get(node.node)?.status === "running");
  const [open, setOpen] = useSessionState<boolean>(
    `${statePrefix}.group-open.${group.key}`,
    group.collapsible ? active : true,
  );

  useEffect(() => {
    if (active) setOpen(true);
  }, [active, setOpen]);

  const { t } = useI18n();

  return (
    <div className="pl-4">
      {(group.collapsible || group.description) && (
        <button
          type="button"
          className="state-layer flex items-center gap-2 w-full min-h-9 py-1.5 pr-2 text-left rounded-sm"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <span className="text-label font-bold text-on-surface-variant">{group.label}</span>
          <span className="text-label text-on-surface-variant">{t("{n} 个节点", { n: group.nodes.length })}</span>
          <Icon name="expand_more" size={18} className={cn("ml-auto text-on-surface-variant transition-transform duration-300 ease-emphasized", open && "rotate-180")} />
        </button>
      )}
      <div className="process-collapse" data-open={open}>
        <div>
          <div className="divide-y divide-outline-variant">
            {group.nodes.map((node) => {
              const item = statuses.get(node.node) || { status: "pending" as const, message: node.description };
              return <NodeRow key={node.node} label={node.label} status={item.status} message={item.message} />;
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

const NODE_STATUS = {
  pending: { icon: "schedule", label: "待运行", className: "text-on-surface-variant bg-surface-high" },
  running: { icon: "sync", label: "运行中", className: "text-primary bg-primary-container" },
  done: { icon: "check", label: "已完成", className: "text-success bg-success-container" },
  skipped: { icon: "remove", label: "已跳过", className: "text-on-surface-variant bg-surface-high" },
  error: { icon: "error", label: "失败", className: "text-error bg-error-container" },
} as const;

function NodeRow({ label, status, message }: { label: string; status: EvaluationNodeStatus; message: string }) {
  const { t } = useI18n();
  const config = NODE_STATUS[status];
  return (
    <div className="relative grid grid-cols-[30px_minmax(0,1fr)_54px] items-start gap-3 py-3 pr-2 min-h-[68px]">
      <span className={cn("flex items-center justify-center w-7 h-7 rounded-sm", config.className)}>
        <Icon name={config.icon} size={17} className={status === "running" ? "md3-node-running" : ""} />
      </span>
      <span className="min-w-0">
        <span className="block text-body font-bold text-on-surface">{label}</span>
        <span className="block mt-0.5 text-body-sm text-on-surface-variant leading-5">{message}</span>
      </span>
      <span className={cn("pt-1 text-label font-bold text-right", status === "running" ? "text-primary" : status === "done" ? "text-success" : status === "error" ? "text-error" : "text-on-surface-variant")}>
        {t(config.label)}
      </span>
      {status === "running" && <span className="md3-running-bar absolute bottom-0 left-0 right-2" />}
    </div>
  );
}
