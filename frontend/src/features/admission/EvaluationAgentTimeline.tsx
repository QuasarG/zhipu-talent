import { useState } from "react";
import AgentWorkingBar from "@/components/ui/AgentWorkingBar";
import Icon from "@/components/ui/Icon";
import ThinkingCard from "@/components/ui/ThinkingCard";
import ToolCallCard from "@/features/chat/ToolCallCard";
import type { ChatSegment, InterviewAssessmentRun, WorkflowNodeEvent } from "@/lib/types";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

type Actor = "evaluator" | "observer" | "system";

const STAGES = [
  { id: "input", label: "输入准备", icon: "inventory_2" },
  { id: "agents", label: "双 Agent 调查", icon: "forum" },
  { id: "validation", label: "结果校验", icon: "fact_check" },
  { id: "decision", label: "硬门槛裁决", icon: "gavel" },
  { id: "report", label: "报告生成", icon: "description" },
] as const;

function actorOf(event: WorkflowNodeEvent): Actor {
  if (event.actor) return event.actor;
  if (event.node_id === "overall_review" || event.event_type === "observer") return "observer";
  if (event.node_id === "input_preparation" || event.node_id === "admission_decision" || event.node_id === "result_formatter") return "system";
  return "evaluator";
}

function stageOf(event: WorkflowNodeEvent): typeof STAGES[number]["id"] {
  if (event.node_id === "input_preparation" || event.node_id === "candidate_preparer") return "input";
  if (event.node_id === "evidence_validation" || event.node_id.startsWith("evidence_repair") || event.event_type === "validation") return "validation";
  if (event.node_id === "admission_decision" || event.node_id === "decision_guard" || event.event_type === "decision") return "decision";
  if (event.node_id === "result_formatter" || event.event_type === "report") return "report";
  return "agents";
}

function latestStageStates(events: WorkflowNodeEvent[]) {
  const states = new Map<string, string>();
  events.forEach((event) => states.set(stageOf(event), event.status));
  return states;
}

function formatTime(value?: string) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
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
        className="state-layer inline-flex h-7 items-center gap-1 rounded-md px-2 text-label text-on-surface-variant"
      >
        <Icon name={open ? "expand_less" : "expand_more"} size={15} />
        {open ? t("收起产物") : t("查看产物")}
      </button>
      {open && (
        <pre className="mt-1 max-h-64 overflow-auto rounded-md bg-surface-low px-3 py-2 font-mono text-xs leading-5 text-on-surface-variant whitespace-pre-wrap break-words">
          {event.error || JSON.stringify(detail, null, 2)}
        </pre>
      )}
    </div>
  );
}

function Activity({ event, isLive }: { event: WorkflowNodeEvent; isLive: boolean }) {
  const { t } = useI18n();
  const actor = actorOf(event);
  const failed = event.status === "failed" || !!event.error;
  const running = isLive && event.status === "running";
  const actorMeta = {
    evaluator: { label: t("评估 Agent"), icon: "manage_search", tone: "bg-primary text-on-primary" },
    observer: { label: t("督导 Agent"), icon: "supervisor_account", tone: "bg-secondary text-on-secondary" },
    system: { label: t("确定性系统"), icon: "rule", tone: "bg-surface-high text-on-surface-variant" },
  }[actor];

  if (event.event_type === "tool" && event.tool) {
    const segment: Extract<ChatSegment, { type: "tool" }> = {
      type: "tool",
      call_id: event.call_id || `${event.node_id}-${event.at || "tool"}`,
      tool: event.tool,
      label: event.label || event.tool,
      status: running ? undefined : failed ? "error" : "ok",
      summary: event.summary,
      detail: Object.keys(event.detail || {}).length ? JSON.stringify(event.detail) : undefined,
      args_summary: event.args_summary,
    };
    return <ToolCallCard segment={segment} />;
  }

  if (event.event_type === "thinking") {
    return <ThinkingCard text={event.summary} streaming={running} />;
  }

  return (
    <article className={cn("relative flex gap-3 pb-5", actor === "observer" && "ml-7")}>
      <div className={cn("relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-md", actorMeta.tone)}>
        <Icon name={actorMeta.icon} size={17} />
      </div>
      <div className={cn(
        "min-w-0 flex-1 rounded-md border px-3 py-2.5",
        actor === "observer" ? "border-secondary/40 bg-secondary-container/30" : "border-outline-variant bg-surface-lowest",
        failed && "border-error/40 bg-error-container/30",
      )}>
        <div className="flex min-w-0 items-center gap-2">
          <span className="text-label font-semibold text-on-surface">{actorMeta.label}</span>
          <span className="truncate text-label text-on-surface-variant">{event.label ? t(event.label) : ""}</span>
          {event.turn && <span className="ml-auto shrink-0 font-mono text-[10px] text-on-surface-variant">T{event.turn}</span>}
          {!event.turn && formatTime(event.at) && <time className="ml-auto shrink-0 font-mono text-[10px] text-on-surface-variant">{formatTime(event.at)}</time>}
        </div>
        <p className="mt-1 text-body-sm leading-5 text-on-surface">{t(event.summary)}</p>
        <EventDetail event={event} />
      </div>
    </article>
  );
}

export default function EvaluationAgentTimeline({ run }: { run: InterviewAssessmentRun }) {
  const { t } = useI18n();
  const events = run.run_trace || [];
  const stageStates = latestStageStates(events);
  // 旧报告在拆分“报告生成”事件之前结束于准入决策，仍应显示完整回放。
  if (run.status === "completed" && stageStates.has("decision") && !stageStates.has("report")) {
    stageStates.set("report", "completed");
  }
  const latestEvent = events.at(-1);
  const live = run.status === "running";

  return (
    <section className="flex min-h-0 flex-1 flex-col" aria-label={t("双 Agent 评估过程")}>
      <div className="border-b border-outline-variant bg-surface-lowest px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-title text-on-surface">{t("双 Agent 评估过程")}</p>
            <p className="mt-0.5 text-label text-on-surface-variant">{t("评估 Agent 调查取证，督导 Agent 独立复核；规则裁决单独执行")}</p>
          </div>
          <div className="flex items-center gap-2 text-label">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-primary-container px-2.5 py-1 text-on-primary-container"><Icon name="manage_search" size={14} />{t("评估 Agent")}</span>
            <Icon name="swap_horiz" size={15} className="text-on-surface-variant" />
            <span className="inline-flex items-center gap-1.5 rounded-full bg-secondary-container px-2.5 py-1 text-on-secondary-container"><Icon name="supervisor_account" size={14} />{t("督导 Agent")}</span>
          </div>
        </div>
        <ol className="mt-3 grid grid-cols-5 gap-1" aria-label={t("评估阶段")}>
          {STAGES.map((stage, index) => {
            const status = stageStates.get(stage.id);
            const active = latestEvent && stageOf(latestEvent) === stage.id && live;
            const done = status === "completed" || status === "done";
            return (
              <li key={stage.id} className="min-w-0">
                <div className={cn("mb-1 h-1 rounded-full", done ? "bg-success" : active ? "bg-primary animate-pulse" : "bg-surface-high")} />
                <div className={cn("flex items-center gap-1 text-[10px] sm:text-label", active ? "text-primary" : done ? "text-on-surface" : "text-on-surface-variant")}>
                  <Icon name={done ? "check" : stage.icon} size={13} className="shrink-0" />
                  <span className="truncate"><span className="hidden sm:inline">{index + 1}. </span>{t(stage.label)}</span>
                </div>
              </li>
            );
          })}
        </ol>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 admission-panel-scrollbar">
        {!events.length ? (
          <div className="flex h-full min-h-48 flex-col items-center justify-center gap-2 text-center text-on-surface-variant">
            <Icon name="hourglass_top" size={28} />
            <p className="text-body-sm text-on-surface">{t("正在等待可用评估槽位")}</p>
            <p className="text-label">{t("开始后，这里会按真实发生顺序记录两个 Agent 的交接与系统裁决")}</p>
          </div>
        ) : (
          <div className="relative mx-auto max-w-3xl before:absolute before:bottom-5 before:left-4 before:top-3 before:w-px before:bg-outline-variant">
            {events.map((event, index) => (
              <Activity key={`${event.node_id}-${event.at || index}-${index}`} event={event} isLive={live && index === events.length - 1} />
            ))}
            {live && <div className="ml-11"><AgentWorkingBar /></div>}
          </div>
        )}
      </div>
    </section>
  );
}
