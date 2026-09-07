import { useState } from "react";
import { ThinkingOrb } from "thinking-orbs";
import Icon from "@/components/ui/Icon";
import ToolCallCard from "@/features/chat/ToolCallCard";
import type { ChatSegment, InterviewAssessmentRun, WorkflowNodeEvent } from "@/lib/types";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

type Actor = "evaluator" | "observer" | "system";
type StageId = "input" | "agents" | "validation" | "decision" | "report";

const STAGES: Array<{ id: StageId; label: string }> = [
  { id: "input", label: "准备输入" },
  { id: "agents", label: "调查与评分" },
  { id: "validation", label: "校验证据" },
  { id: "decision", label: "规则裁决" },
  { id: "report", label: "生成报告" },
];

const AGENT_LANES: Array<{ id: "system" | "evaluator" | "observer" | "decision"; label: string; role: string; icon: string; accent: string }> = [
  { id: "system", label: "材料中枢", role: "整理输入与证据包", icon: "inventory_2", accent: "text-on-surface-variant" },
  { id: "evaluator", label: "评估 Agent", role: "并行完成岗位评分", icon: "manage_search", accent: "text-primary" },
  { id: "observer", label: "督导 Agent", role: "复核证据与风险", icon: "supervisor_account", accent: "text-secondary" },
  { id: "decision", label: "裁决与报告", role: "硬门槛 + 结果输出", icon: "rule", accent: "text-tertiary" },
];

function actorOf(event: WorkflowNodeEvent): Actor {
  if (event.actor) return event.actor;
  if (event.node_id === "overall_review" || event.event_type === "observer") return "observer";
  if (["input_preparation", "candidate_preparer", "admission_decision", "decision_guard", "result_formatter"].includes(event.node_id)) return "system";
  return "evaluator";
}

function stageOf(event: WorkflowNodeEvent): StageId {
  if (event.node_id === "input_preparation" || event.node_id === "candidate_preparer") return "input";
  if (event.node_id === "evidence_validation" || event.node_id.startsWith("evidence_repair") || event.event_type === "validation") return "validation";
  if (event.node_id === "admission_decision" || event.node_id === "decision_guard" || event.event_type === "decision") return "decision";
  if (event.node_id === "result_formatter" || event.event_type === "report") return "report";
  return "agents";
}

function stageStates(events: WorkflowNodeEvent[], completed: boolean) {
  const states = new Map<StageId, string>();
  events.forEach((event) => states.set(stageOf(event), event.status));
  if (completed && states.has("decision") && !states.has("report")) states.set("report", "completed");
  return states;
}

function laneState(events: WorkflowNodeEvent[], lane: typeof AGENT_LANES[number], completed: boolean) {
  const related = events.filter((event) => {
    if (lane.id === "decision") return stageOf(event) === "decision" || stageOf(event) === "report";
    return lane.id === actorOf(event);
  });
  const latest = related.at(-1);
  if (latest?.status === "failed" || latest?.error) return "failed" as const;
  if (completed && related.length) return "done" as const;
  if (latest?.status === "running") return "running" as const;
  if (related.length) return "done" as const;
  return "pending" as const;
}

function formatTime(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function actorLabel(actor: Actor, t: (value: string) => string) {
  if (actor === "observer") return t("督导 Agent");
  if (actor === "system") return t("系统编排");
  return t("评估 Agent");
}

function nextActorLabel(events: WorkflowNodeEvent[], index: number, t: (value: string) => string) {
  const current = actorOf(events[index]);
  const next = events.slice(index + 1).map(actorOf).find((actor) => actor !== current);
  return next ? actorLabel(next, t) : t("继续处理");
}

function FriendlyDetail({ detail }: { detail: Record<string, unknown> }) {
  const { t } = useI18n();
  const tasks = Array.isArray(detail.tasks) ? detail.tasks as Array<Record<string, unknown>> : [];
  const mappings = Array.isArray(detail.task_mappings) ? detail.task_mappings as Array<Record<string, unknown>> : [];
  const corrections = Array.isArray(detail.corrections) ? detail.corrections as Array<Record<string, unknown>> : [];

  if (tasks.length) {
    return (
      <div className="divide-y divide-outline-variant">
        {tasks.map((task, index) => {
          const data = task.detail as Record<string, unknown> | undefined;
          return (
            <div key={`${String(task.label)}-${index}`} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 py-2 first:pt-0 last:pb-0">
              <div className="min-w-0">
                <p className="truncate text-label font-medium text-on-surface">{String(task.label || t("核心任务 {n}", { n: index + 1 }))}</p>
                <p className="mt-0.5 text-label leading-4 text-on-surface-variant">{String(data?.reasoning_summary || task.summary || "")}</p>
              </div>
              {typeof data?.level === "number" && <span className="font-mono text-label text-on-surface">L{data.level as number}</span>}
            </div>
          );
        })}
      </div>
    );
  }
  if (mappings.length) {
    return (
      <div className="space-y-2">
        {mappings.map((mapping, index) => (
          <div key={`${String(mapping.task_id)}-${index}`}>
            <p className="text-label font-medium text-on-surface">{String(mapping.task_id || t("任务 {n}", { n: index + 1 }))}</p>
            <p className="mt-0.5 text-label leading-4 text-on-surface-variant">{String(mapping.mapping_reason || "")}</p>
          </div>
        ))}
      </div>
    );
  }
  if (corrections.length) {
    return (
      <div className="space-y-2">
        {corrections.map((correction, index) => (
          <p key={index} className="text-label leading-4 text-on-surface-variant">
            <span className="font-medium text-on-surface">{String(correction.task_id || t("任务"))}</span>
            {` · L${String(correction.original_level ?? "—")} → L${String(correction.revised_level ?? "—")} · ${String(correction.reason || "")}`}
          </p>
        ))}
      </div>
    );
  }
  return <pre className="max-h-52 overflow-auto font-mono text-xs leading-5 text-on-surface-variant whitespace-pre-wrap break-words">{JSON.stringify(detail, null, 2)}</pre>;
}

function EventDetail({ event }: { event: WorkflowNodeEvent }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const detail = event.detail || {};
  if (!Object.keys(detail).length && !event.error) return null;
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="state-layer -ml-1 inline-flex h-7 items-center gap-1 rounded-md px-1.5 text-label font-medium text-on-surface-variant focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary"
        aria-expanded={open}
      >
        <Icon name={open ? "keyboard_arrow_up" : "keyboard_arrow_down"} size={15} />
        {open ? t("收起详情") : t("查看详情")}
      </button>
      {open && (
        <div className="mt-2 border-t border-outline-variant pt-2">
          {event.error ? <p className="text-label text-error">{event.error}</p> : <FriendlyDetail detail={detail} />}
        </div>
      )}
    </div>
  );
}

function AgentEvent({ event, live, handoff }: { event: WorkflowNodeEvent; live: boolean; handoff: string }) {
  const { t } = useI18n();
  const actor = actorOf(event);
  const failed = event.status === "failed" || !!event.error;
  const meta = actor === "observer"
    ? { label: t("督导 Agent"), icon: "supervisor_account", accent: "text-secondary", surface: "bg-secondary-container/35" }
    : { label: t("评估 Agent"), icon: "manage_search", accent: "text-primary", surface: "bg-surface-low" };

  if (event.event_type === "tool" && event.tool) {
    const segment: Extract<ChatSegment, { type: "tool" }> = {
      type: "tool",
      call_id: event.call_id || `${event.node_id}-${event.at || "tool"}`,
      tool: event.tool,
      label: event.label || event.tool,
      status: live ? undefined : failed ? "error" : "ok",
      summary: event.summary,
      detail: Object.keys(event.detail || {}).length ? JSON.stringify(event.detail) : undefined,
      args_summary: event.args_summary,
    };
    return (
      <article className="py-3">
        <div className="mb-1 flex items-center gap-2 text-[10px] text-on-surface-variant">
          <span className="font-semibold text-primary">{meta.label}</span>
          <Icon name="arrow_forward" size={12} />
          <span>{handoff}</span>
          {formatTime(event.at) && <time className="ml-auto font-mono opacity-70">{formatTime(event.at)}</time>}
        </div>
        <ToolCallCard segment={segment} />
      </article>
    );
  }

  return (
    <article className={cn("group grid grid-cols-[24px_minmax(0,1fr)] gap-2.5 py-3", actor === "observer" && "ml-5")}>
      <div className={cn("mt-0.5 flex h-6 w-6 items-center justify-center rounded-md", meta.surface, meta.accent)}>
        {live ? <ThinkingOrb state="shaping" size={20} aria-label={t("正在思考")} /> : <Icon name={meta.icon} size={15} />}
      </div>
      <div className={cn("min-w-0", live && "rounded-md bg-primary-container/25 px-3 py-2 -my-2", failed && "text-error")}>
        <div className="flex items-baseline gap-2">
          <span className={cn("text-label font-semibold", meta.accent)}>{meta.label}</span>
          <span className="text-[10px] text-on-surface-variant">{t("→")} {handoff}</span>
          <span className="truncate text-label text-on-surface-variant">{event.label ? t(event.label) : ""}</span>
          {formatTime(event.at) && <time className="ml-auto shrink-0 font-mono text-[10px] text-on-surface-variant opacity-70">{formatTime(event.at)}</time>}
        </div>
        <p className="mt-0.5 text-body-sm leading-5 text-on-surface">{t(event.summary)}</p>
        <EventDetail event={event} />
      </div>
    </article>
  );
}

function SystemEvent({ event }: { event: WorkflowNodeEvent }) {
  const { t } = useI18n();
  const failed = event.status === "failed" || !!event.error;
  return (
    <article className="grid grid-cols-[24px_minmax(0,1fr)] items-start gap-2.5 py-2.5">
      <span className={cn("mt-0.5 flex h-5 w-5 items-center justify-center rounded-full", failed ? "bg-error-container text-error" : "bg-success-container text-success")}>
        <Icon name={failed ? "error" : "check"} size={12} />
      </span>
      <div className="min-w-0">
        <div className="flex items-baseline gap-2">
          <span className="text-label font-medium text-on-surface">{event.label ? t(event.label) : t("系统检查")}</span>
          <span className="truncate text-label text-on-surface-variant">{t(event.summary)}</span>
          {formatTime(event.at) && <time className="ml-auto shrink-0 font-mono text-[10px] text-on-surface-variant opacity-70">{formatTime(event.at)}</time>}
        </div>
        <EventDetail event={event} />
      </div>
    </article>
  );
}

function ActiveAgentBanner({ event, live }: { event?: WorkflowNodeEvent; live: boolean }) {
  const { t } = useI18n();
  const actor = event ? actorOf(event) : "system";
  const label = actorLabel(actor, t);
  return (
    <div className="flex items-center gap-3 border-b border-outline-variant bg-surface-lowest px-4 py-2.5">
      <span className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-container text-primary">
        {live ? <ThinkingOrb state="shaping" size={20} aria-label={t("正在工作")} /> : <Icon name="check_circle" size={17} />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[10px] font-semibold uppercase tracking-[0.08em] text-on-surface-variant">{t("当前正在工作")}</p>
        <p className="truncate text-body-sm font-semibold text-on-surface">{label}</p>
      </div>
      <p className="max-w-[55%] truncate text-label text-on-surface-variant">{event?.summary ? t(event.summary) : t("等待 Agent 接收任务")}</p>
    </div>
  );
}

function AgentLanes({ events, completed }: { events: WorkflowNodeEvent[]; completed: boolean }) {
  const { t } = useI18n();
  return (
    <div className="grid grid-cols-2 gap-2 border-b border-outline-variant bg-surface-low/45 px-4 py-3 lg:grid-cols-4" aria-label={t("多 Agent 编排") }>
      {AGENT_LANES.map((lane, index) => {
        const state = laneState(events, lane, completed);
        const stateLabel = state === "running" ? t("运行中") : state === "done" ? t("已完成") : state === "failed" ? t("失败") : t("等待");
        return (
          <div key={lane.id} className="relative min-w-0 rounded-md border border-outline-variant bg-surface-lowest px-2.5 py-2">
            {index > 0 && <span className="pointer-events-none absolute -left-2.5 top-1/2 hidden h-px w-2 bg-outline-variant lg:block" aria-hidden="true" />}
            <div className="flex items-center gap-2">
              <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-surface-high", lane.accent)}>
                {state === "running" ? <ThinkingOrb state="shaping" size={20} aria-label={t("正在运行")} /> : <Icon name={lane.icon} size={15} />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-label font-semibold text-on-surface">{t(lane.label)}</span>
                <span className="block truncate text-[10px] text-on-surface-variant">{t(lane.role)}</span>
              </span>
              <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", state === "running" ? "animate-pulse bg-primary" : state === "done" ? "bg-success" : state === "failed" ? "bg-error" : "bg-outline-variant")} title={stateLabel} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function EvaluationAgentTimeline({ run, compact = false }: { run: InterviewAssessmentRun; compact?: boolean }) {
  const { t } = useI18n();
  // 透明模式保留完整事件顺序；不要按 node_id 折叠，否则同一 Agent 的交接信息会被吞掉。
  const events = run.run_trace || [];
  const states = stageStates(events, run.status === "completed");
  const latest = events.at(-1);
  const live = run.status === "running";
  const currentStage = latest ? STAGES.find((stage) => stage.id === stageOf(latest)) : STAGES[0];
  const status = run.status === "failed"
    ? { label: "失败", shell: "bg-error-container text-error", dot: "bg-error" }
    : run.status === "cancelled"
      ? { label: "已停止", shell: "bg-surface-high text-on-surface-variant", dot: "bg-outline" }
      : run.status === "queued"
        ? { label: "排队中", shell: "bg-surface-high text-on-surface-variant", dot: "bg-outline" }
        : live
          ? { label: "运行中", shell: "bg-primary-container text-on-primary-container", dot: "animate-pulse bg-primary" }
          : { label: "已完成", shell: "bg-surface-high text-on-surface-variant", dot: "bg-success" };

  return (
    <section className="flex min-h-0 flex-1 flex-col" aria-label={t("评估协作记录")}>
      <header className="shrink-0 border-b border-outline-variant px-4 pb-3 pt-3.5">
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-title text-on-surface">{t("评估协作记录")}</h2>
            <p className="mt-0.5 truncate text-label text-on-surface-variant">
              {live ? t("当前：{stage}", { stage: t(currentStage?.label || "准备输入") }) : t("评估 Agent → 督导 Agent → 规则裁决")}
            </p>
          </div>
          <span className={cn("inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-label font-medium", status.shell)}>
            <span className={cn("h-1.5 w-1.5 rounded-full", status.dot)} />
            {t(status.label)}
          </span>
        </div>

        <ol className="mt-3 flex" aria-label={t("评估阶段")}>
          {STAGES.map((stage, index) => {
            const status = states.get(stage.id);
            const active = live && currentStage?.id === stage.id;
            const done = status === "completed" || status === "done";
            return (
              <li key={stage.id} className="relative min-w-0 flex-1 pt-3 first:flex-none first:w-[13%] last:flex-none last:w-[13%]">
                {index > 0 && <span className={cn("absolute left-0 right-1/2 top-[3px] h-px", done || active ? "bg-on-surface" : "bg-outline-variant")} />}
                {index < STAGES.length - 1 && <span className={cn("absolute left-1/2 right-0 top-[3px] h-px", done ? "bg-on-surface" : "bg-outline-variant")} />}
                <span className={cn("absolute left-1/2 top-0 h-[7px] w-[7px] -translate-x-1/2 rounded-full ring-2 ring-surface-lowest", active ? "bg-primary" : done ? "bg-on-surface" : "bg-outline-variant")} />
                <span className={cn("block truncate text-center text-[10px] leading-4", active || done ? "font-medium text-on-surface" : "text-on-surface-variant")}>
                  {t(stage.label)}
                </span>
              </li>
            );
          })}
        </ol>
      </header>

      <ActiveAgentBanner event={latest} live={live} />
      <AgentLanes events={events} completed={run.status === "completed"} />

      <div className={cn("min-h-0 flex-1 overflow-y-auto admission-panel-scrollbar", compact ? "px-4 py-1" : "px-5 py-2")}>
        {!events.length ? (
          <div className="flex h-full min-h-48 flex-col items-center justify-center gap-2 text-center text-on-surface-variant">
            <Icon name="hourglass_top" size={26} />
            <p className="text-body-sm text-on-surface">{t("等待评估开始")}</p>
            <p className="max-w-sm text-label">{t("开始后将记录 Agent 交接、证据校验与规则裁决")}</p>
          </div>
        ) : (
          <div className={cn("mx-auto divide-y divide-outline-variant", compact ? "max-w-none" : "max-w-4xl")}>
            {events.map((event, index) => actorOf(event) === "system" ? (
              <SystemEvent key={`${event.node_id}-${event.at || index}`} event={event} />
            ) : (
              <AgentEvent key={`${event.node_id}-${event.at || index}`} event={event} handoff={nextActorLabel(events, index, t)} live={live && index === events.length - 1 && event.status === "running"} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
