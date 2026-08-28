import { useEffect, useId, useState, type ReactNode } from "react";
import type { AdmissionGraphNode } from "@/features/admission/AdmissionWorkflowGraph";
import { computeScoreBreakdown } from "@/features/talentEvaluation/talentEvaluationModel";
import type { InterviewAssessment, InterviewAssessmentRun, JdEntry } from "@/lib/types";
import { StatusChip } from "@/components/ui/Chip";
import Icon from "@/components/ui/Icon";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";
import { ADMISSION_SCORE_LINE } from "./talentEvaluationModel";

export const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "cancelled"]);

export const RUN_STATUS_LABEL: Record<string, string> = {
  queued: "排队中",
  running: "评估中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已停止",
};

export const RUN_STATUS_TONE: Record<string, "primary" | "success" | "error" | "neutral"> = {
  queued: "neutral",
  running: "primary",
  completed: "success",
  failed: "error",
  cancelled: "neutral",
};

export interface EvidenceView {
  quote?: string;
  evidence_type?: "direct" | "transferable" | "background";
  confidence?: "high" | "medium" | "low";
  relevance?: string;
}

export interface TaskAssessmentView {
  task_id?: string;
  level?: number;
  confidence?: "high" | "medium" | "low";
  reasoning_summary?: string;
  transfer_boundary?: string;
  evidence?: EvidenceView[];
  risks?: string[];
}

type Translate = ReturnType<typeof useI18n>["t"];

export function confidenceLabel(value: string | undefined, t: Translate) {
  return value === "high" ? t("高置信") : value === "medium" ? t("中置信") : value === "low" ? t("低置信") : "—";
}

const IMPORTANCE_META: Record<string, { label: string; icon: string; className: string }> = {
  primary: { label: "首要指标", icon: "grade", className: "importance-primary" },
  major: { label: "主要指标", icon: "trending_up", className: "importance-major" },
  supporting: { label: "补充指标", icon: "badge", className: "importance-supporting" },
};

/**
 * 准入评估报告正文：二元结论、加权总分与计算明细、核心任务证据、
 * 纠错记录、面试重点、模型与降级记录（docs/rebuild.md §3.3 / §7）。
 */
export default function AdmissionReport({
  assessment,
  jd,
  run,
}: {
  assessment: InterviewAssessment;
  jd?: JdEntry;
  run?: InterviewAssessmentRun;
}) {
  const { t } = useI18n();
  const tasks = (assessment.task_assessments || []) as TaskAssessmentView[];
  const breakdown = computeScoreBreakdown(tasks, jd?.assessment_card);
  const cardTask = (taskId?: string) =>
    jd?.assessment_card?.core_tasks.find((item) => item.id === taskId);
  const decisionReason = [...(assessment.run_trace || [])]
    .reverse()
    .find((event) => event.node_id === "admission_decision")?.summary;
  const degradedCount = (assessment.model_usage || []).filter(
    (item) => item.fallback_reason && item.fallback_reason !== "none",
  ).length;
  const models = [...new Set((assessment.model_usage || []).map((item) => item.model))];
  const focusByTask = new Map(
    ((assessment.interview_focus || []) as Array<Record<string, string>>).map((item) => [
      item.task_id,
      item.focus,
    ]),
  );
  const taskKeys = tasks.map((task, index) => task.task_id || `task-${index}`);
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const [scoreBreakdownOpen, setScoreBreakdownOpen] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);

  useEffect(() => {
    setExpandedTaskId(null);
    setScoreBreakdownOpen(false);
    setAuditOpen(false);
  }, [assessment.id]);

  return (
    <section className="flex flex-col gap-5">
      {!assessment.is_valid && (
        <div className="flex items-start gap-2 rounded-md bg-warning/10 border border-warning/40 px-3 py-2.5 text-body-sm text-on-surface">
          <Icon name="history" size={17} className="mt-0.5 shrink-0 text-warning" />
          <div>
            <p className="font-medium">{t("报告已失效，需要重评")}</p>
            {assessment.invalid_reason && (
              <p className="mt-0.5 text-label text-on-surface-variant">{assessment.invalid_reason}</p>
            )}
          </div>
        </div>
      )}

      <div className="admission-decision-summary rounded-md border border-outline-variant bg-surface-lowest px-4 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <StatusChip tone={assessment.decision === "interview" ? "success" : "error"} variant="filled" icon={assessment.decision === "interview" ? "check_circle" : "error"}>
              {assessment.decision === "interview" ? t("进入面试") : t("不进入面试")}
            </StatusChip>
            <p className="mt-3 max-w-2xl text-body-sm text-on-surface-variant">
              {decisionReason || t("根据核心任务能力与简历证据生成准入判断")}
            </p>
          </div>
          <div className="shrink-0 text-left sm:text-right">
            <div className="flex items-baseline gap-1.5 sm:justify-end">
              <span className="text-headline tabular-nums">{assessment.total_score.toFixed(1)}</span>
              <span className="text-body-sm text-on-surface-variant">{t("/100 加权总分")}</span>
            </div>
            <p className="mt-1 text-label text-on-surface-variant">
              {t("{n}/{total} 条件满足", {
                n: [breakdown.primaryThresholdMet, breakdown.scoreThresholdMet].filter(Boolean).length,
                total: 2,
              })}
            </p>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 border-t border-outline-variant pt-3 text-label">
          <ThresholdItem met={breakdown.primaryThresholdMet} label={t("首要任务等级 ≥ 2")} />
          <ThresholdItem met={breakdown.scoreThresholdMet} label={t("加权总分 ≥ {n}", { n: ADMISSION_SCORE_LINE })} />
        </div>
      </div>

      <AnimatedDisclosure
        icon="list_checks"
        title={t("评分构成")}
        summary={t("{n} 项核心任务加权汇总", { n: breakdown.rows.length })}
        open={scoreBreakdownOpen}
        onToggle={() => setScoreBreakdownOpen((value) => !value)}
      >
        <div className="grid grid-cols-1 gap-x-5 gap-y-1.5 px-3.5 py-3 sm:grid-cols-2">
          {breakdown.rows.map((row) => (
            <div key={row.taskId} className="flex min-w-0 items-baseline gap-2 text-label text-on-surface-variant">
              <span className="w-7 shrink-0 font-mono text-on-surface">L{row.level}</span>
              <span className="min-w-0 flex-1 truncate">{row.title}</span>
              <span className="shrink-0 tabular-nums">{row.coefficient}×{Math.round(row.weighted)}</span>
            </div>
          ))}
          <div className="flex items-baseline gap-2 border-t border-outline-variant pt-1.5 text-label sm:col-span-2">
            <span className="w-7 shrink-0" />
            <span className="flex-1">{t("加权总分")}</span>
            <span className="shrink-0 font-medium tabular-nums text-on-surface">{breakdown.total.toFixed(1)}</span>
          </div>
        </div>
      </AnimatedDisclosure>

      <section>
        <div className="mb-3 flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <h3 className="text-title">{t("核心任务评分")}</h3>
          <span className="text-label text-on-surface-variant">{t("按重要性逐项查看，点击任务展开证据")}</span>
        </div>
        <div className="flex flex-col gap-2">
          {tasks.map((task, index) => {
            const taskKey = taskKeys[index];
            const cardTaskMeta = cardTask(task.task_id);
            const isOpen = taskKey === expandedTaskId;
            return (
              <TaskAssessmentCard
                key={taskKey}
                task={task}
                title={cardTaskMeta?.title || task.task_id || t("核心任务 {n}", { n: index + 1 })}
                importance={cardTaskMeta?.importance}
                open={isOpen}
                onToggle={() => setExpandedTaskId(isOpen ? null : taskKey)}
                t={t}
              />
            );
          })}
        </div>
      </section>

      {assessment.decision === "interview" && !!focusByTask.size && (
        <div className="rounded-md border border-outline-variant bg-surface-low px-3.5 py-3">
          <div className="flex items-center gap-2">
            <Icon name="target" size={17} className="text-success" />
            <p className="text-body-sm font-medium">{t("针对性面试重点")}</p>
          </div>
          <ul className="mt-2 space-y-1.5 pl-6 text-label text-on-surface-variant">
            {[...focusByTask.entries()].slice(0, 3).map(([taskId, focus]) => (
              <li key={taskId}>
                <span className="font-medium text-on-surface">{cardTask(taskId)?.title || taskId}</span>
                {focus ? `：${focus}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      <AnimatedDisclosure
        icon="history"
        title={t("模型与审计")}
        summary={(
          <span className="min-w-0 truncate text-on-surface-variant">
            {models.join(" · ") || "—"}
            {!!degradedCount && (
              <span className="ml-2 inline-flex items-center gap-1 text-warning">
                <Icon name="alert-triangle" size={13} />
                {t("{n} 次降级", { n: degradedCount })}
              </span>
            )}
          </span>
        )}
        open={auditOpen}
        onToggle={() => setAuditOpen((value) => !value)}
        compact
      >
        <div className="px-3.5 py-3">
          {!!assessment.review_corrections.length && (
            <div>
              <p className="text-label font-semibold">{t("总审纠错记录")}</p>
              <div className="mt-2 flex flex-col gap-2">
                {(assessment.review_corrections as Array<Record<string, unknown>>).map((correction, index) => (
                  <div key={index} className="text-label text-on-surface-variant">
                    <span className="font-medium text-on-surface">
                      {cardTask(String(correction.task_id || ""))?.title || String(correction.task_id || t("任务"))}
                    </span>
                    <span className="mx-1 tabular-nums">{String(correction.original_level ?? "—")} → {String(correction.revised_level ?? "—")}</span>
                    <span>{String(correction.reason || "")}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {run?.error_message && (
            <p className="mt-3 rounded-md bg-error-container p-3 text-body-sm text-on-error-container">{run.error_message}</p>
          )}
          {!assessment.review_corrections.length && !run?.error_message && (
            <p className="text-label text-on-surface-variant">{t("本次运行没有额外审计事项")}</p>
          )}
        </div>
      </AnimatedDisclosure>
    </section>
  );
}

function ThresholdItem({ met, label }: { met: boolean; label: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5", met ? "text-success" : "text-error")}>
      <Icon name={met ? "check_circle" : "close"} size={15} />
      {label}
    </span>
  );
}

function AnimatedDisclosure({
  icon,
  title,
  summary,
  open,
  onToggle,
  compact = false,
  children,
}: {
  icon: string;
  title: string;
  summary?: ReactNode;
  open: boolean;
  onToggle: () => void;
  compact?: boolean;
  children: ReactNode;
}) {
  const contentId = useId();
  return (
    <section className="admission-disclosure rounded-md border border-outline-variant bg-surface-lowest" data-open={open}>
      <button
        type="button"
        className={cn(
          "flex w-full cursor-pointer items-center gap-2 px-3.5 py-3 text-left",
          compact ? "text-label" : "text-body-sm",
        )}
        aria-expanded={open}
        aria-controls={contentId}
        onClick={onToggle}
      >
        <Icon name={icon} size={compact ? 16 : 17} className="shrink-0 text-on-surface-variant" />
        <span className="shrink-0 font-medium">{title}</span>
        {summary && <span className="min-w-0 flex-1 truncate text-label text-on-surface-variant">{summary}</span>}
        <Icon
          name="expand_more"
          size={16}
          className="admission-disclosure-chevron ml-auto shrink-0 text-on-surface-variant"
        />
      </button>
      <div id={contentId} className="admission-disclosure-content">
        <div>
          <div className="border-t border-outline-variant">{children}</div>
        </div>
      </div>
    </section>
  );
}

function TaskAssessmentCard({
  task,
  title,
  importance,
  open,
  onToggle,
  t,
}: {
  task: TaskAssessmentView;
  title: string;
  importance?: string;
  open: boolean;
  onToggle: () => void;
  t: Translate;
}) {
  const contentId = useId();
  const evidence = task.evidence || [];
  const level = task.level ?? 0;
  const importanceMeta = IMPORTANCE_META[importance || ""] || {
    label: "评价指标",
    icon: "badge",
    className: "importance-supporting",
  };
  return (
    <div className={cn(
      "admission-task-card relative overflow-hidden rounded-md border bg-surface-lowest",
      importanceMeta.className,
      open ? "is-selected border-outline bg-surface-lowest shadow-[var(--shadow-1)]" : "border-outline-variant hover:border-outline",
    )} data-open={open}>
      <button
        type="button"
        className="flex min-h-[92px] w-full cursor-pointer items-center gap-3 px-3.5 py-3 text-left"
        aria-expanded={open}
        aria-controls={contentId}
        aria-label={`${title}，契合度 L${level}/4，${open ? "收起证据" : "展开证据"}`}
        onClick={onToggle}
      >
        <span className="admission-task-importance-icon flex h-9 w-9 shrink-0 items-center justify-center rounded-md">
          <Icon name={importanceMeta.icon} size={18} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex min-w-0 items-center gap-2">
            <span className="admission-task-importance-label shrink-0 text-[11px] font-semibold tracking-[0.06em]">
              {t(importanceMeta.label)}
            </span>
            <span className="truncate text-body-sm font-medium text-on-surface">{title}</span>
          </span>
          <span className="mt-1 block truncate text-label leading-4 text-on-surface-variant">
            {task.reasoning_summary || t("暂无推理摘要")}
          </span>
          <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-on-surface-variant">
            <span>{confidenceLabel(task.confidence, t)}</span>
            {!!evidence.length && <span>{t("{n} 条证据", { n: evidence.length })}</span>}
          </span>
        </span>
        <span className="shrink-0 text-right">
          <span className="text-[10px] text-on-surface-variant">{t("契合度")}</span>
          <span className={cn(
            "mt-1 block rounded-sm px-2 py-1 font-mono text-label font-medium tabular-nums",
            level >= 2 ? "bg-success-container text-success" : "bg-warning-container text-warning",
          )}>
            L{level}<span className="ml-0.5 opacity-70">/4</span>
          </span>
        </span>
        <Icon
          name="expand_more"
          size={18}
          className={cn("admission-task-chevron shrink-0 text-on-surface-variant", open && "is-open")}
        />
      </button>
      <div id={contentId} role="region" aria-label={t("{title} 证据详情", { title })} className="admission-task-drawer-content" aria-hidden={!open}>
        <div>
          <TaskAssessmentDrawerContent task={task} t={t} />
        </div>
      </div>
    </div>
  );
}

function TaskAssessmentDrawerContent({
  task,
  t,
}: {
  task: TaskAssessmentView;
  t: Translate;
}) {
  const evidence = task.evidence || [];
  return (
    <div className="admission-task-drawer-body border-t border-outline-variant px-4 py-4">
      <div className="flex flex-col gap-3">
        {task.transfer_boundary && (
          <p className="rounded-sm bg-surface-low px-2.5 py-2 text-label leading-4 text-on-surface-variant">
            <span className="font-medium text-on-surface">{t("迁移边界")}：</span>{task.transfer_boundary}
          </p>
        )}
        {!!evidence.length && (
          <div className="flex flex-col gap-2">
            <p className="text-label font-semibold">{t("关键证据")}</p>
            {evidence.slice(0, 3).map((item, index) => (
              <EvidenceQuote key={`${item.quote}-${index}`} evidence={item} />
            ))}
          </div>
        )}
        {!!task.risks?.length && (
          <div>
            <p className="text-label font-semibold">{t("能力缺口")}</p>
            <ul className="mt-1.5 list-disc space-y-1 pl-4 text-label text-on-surface-variant">
              {task.risks.slice(0, 3).map((risk) => <li key={risk}>{risk}</li>)}
            </ul>
          </div>
        )}
        {!task.transfer_boundary && !evidence.length && !task.risks?.length && (
          <p className="text-label text-on-surface-variant">{t("该任务没有额外展开信息")}</p>
        )}
      </div>
    </div>
  );
}

export function EvidenceQuote({ evidence }: { evidence: EvidenceView }) {
  const { t } = useI18n();
  const meta = {
    direct: { label: t("直接证据"), className: "bg-primary text-on-primary" },
    transferable: { label: t("可迁移证据"), className: "border border-outline text-on-surface" },
    background: { label: t("背景证据"), className: "bg-surface-high text-on-surface-variant" },
  }[evidence.evidence_type || "background"];
  return (
    <div className="rounded-md bg-surface-low px-3 py-2.5">
      <span className={cn("inline-flex h-5 items-center rounded-full px-2 text-[10px] font-medium", meta.className)}>{meta.label}</span>
      <q className="mt-2 block text-body-sm leading-relaxed text-on-surface">{evidence.quote || t("未提供引用")}</q>
      {evidence.relevance && <p className="mt-1.5 text-label leading-4 text-on-surface-variant">{evidence.relevance}</p>}
    </div>
  );
}

export function NodeInspector({ node }: { node: AdmissionGraphNode | null }) {
  const { t } = useI18n();
  if (!node) {
    return (
      <div className="flex h-full min-h-32 flex-col items-center justify-center gap-2 text-on-surface-variant">
        <Icon name="inspect" size={28} />
        <p className="text-body-sm">{t("选择一个节点查看详情")}</p>
      </div>
    );
  }
  const detail = node.event?.detail || {};
  const taskDetail = detail as Record<string, unknown>;
  const evidence = Array.isArray(taskDetail.evidence) ? taskDetail.evidence as EvidenceView[] : [];
  const mappings = Array.isArray(taskDetail.task_mappings) ? taskDetail.task_mappings as Array<Record<string, unknown>> : [];
  return (
    <section>
      <div className="flex items-center gap-2">
        <span className={cn(
          "h-2.5 w-2.5 rounded-full",
          node.status === "failed" ? "bg-error" : node.status === "running" ? "bg-primary animate-pulse" : "border border-outline",
        )} />
        <p className="text-title">{node.label}</p>
        <span className="ml-auto text-label text-on-surface-variant">{t(RUN_STATUS_LABEL[node.status] || node.status)}</span>
      </div>
      <p className="mt-2 text-body-sm text-on-surface-variant">{node.summary}</p>

      {typeof taskDetail.level === "number" && (
        <div className="mt-4 flex items-end gap-2">
          <span className="text-headline font-mono tabular-nums">{taskDetail.level as number}</span>
          <span className="pb-1 text-label text-on-surface-variant">
            {t("/4 能力等级 · {confidence}", { confidence: confidenceLabel(taskDetail.confidence as TaskAssessmentView["confidence"], t) })}
          </span>
        </div>
      )}
      {typeof taskDetail.reasoning_summary === "string" && (
        <div className="mt-3">
          <p className="text-label font-semibold">{t("判断依据")}</p>
          <p className="mt-1 text-body-sm text-on-surface-variant">{taskDetail.reasoning_summary}</p>
        </div>
      )}
      {!!evidence.length && (
        <div className="mt-3 flex flex-col gap-2">
          <p className="text-label font-semibold">{t("引用证据")}</p>
          {evidence.map((item, index) => <EvidenceQuote key={`${item.quote}-${index}`} evidence={item} />)}
        </div>
      )}
      {!!mappings.length && (
        <div className="mt-3 flex flex-col gap-2">
          <p className="text-label font-semibold">{t("能力映射")}</p>
          {mappings.map((mapping, index) => (
            <div key={index} className="border-t border-outline-variant pt-2">
              <p className="text-body-sm font-medium">{String(mapping.task_id || t("任务 {n}", { n: index + 1 }))}</p>
              {Array.isArray(mapping.candidate_evidence) && <p className="mt-1 text-label text-on-surface-variant">{mapping.candidate_evidence.map(String).join("；")}</p>}
              {typeof mapping.mapping_reason === "string" && <p className="mt-1 text-body-sm text-on-surface-variant">{mapping.mapping_reason}</p>}
            </div>
          ))}
        </div>
      )}
      {node.event?.error && <p className="mt-3 rounded-md bg-error-container p-3 text-body-sm text-on-error-container">{node.event.error}</p>}
      {!Object.keys(detail).length && node.kind !== "source" && (
        <p className="mt-4 text-label text-on-surface-variant">{t("该节点当前没有额外产物。")}</p>
      )}
    </section>
  );
}
