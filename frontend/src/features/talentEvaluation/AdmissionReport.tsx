import type { AdmissionGraphNode } from "@/features/admission/AdmissionWorkflowGraph";
import { computeScoreBreakdown } from "@/features/talentEvaluation/talentEvaluationModel";
import type { InterviewAssessment, InterviewAssessmentRun, JdEntry } from "@/lib/types";
import { StatusChip } from "@/components/ui/Chip";
import Icon from "@/components/ui/Icon";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

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

const IMPORTANCE_LABEL: Record<string, string> = {
  primary: "首要",
  major: "主要",
  supporting: "补充",
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

  return (
    <section className="flex flex-col gap-4">
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

      <div className="flex items-center gap-2">
        <StatusChip tone={assessment.decision === "interview" ? "success" : "error"} variant="filled" icon={assessment.decision === "interview" ? "check_circle" : "error"}>
          {assessment.decision === "interview" ? t("进入面试") : t("不进入面试")}
        </StatusChip>
        <span className="text-label text-on-surface-variant">
          {assessment.candidate_name || t("候选人")} × {assessment.jd_title || jd?.title || t("岗位")}
        </span>
      </div>

      <div>
        <div className="flex items-baseline gap-1">
          <span className="text-headline tabular-nums">{assessment.total_score.toFixed(1)}</span>
          <span className="text-body-sm text-on-surface-variant">{t("/100 加权总分")}</span>
        </div>
        {decisionReason && <p className="mt-1.5 text-body-sm text-on-surface-variant">{decisionReason}</p>}
        <div className="mt-2 flex flex-wrap items-center gap-2 text-label">
          <span className={cn("inline-flex items-center gap-1", breakdown.primaryThresholdMet ? "text-success" : "text-error")}>
            <Icon name={breakdown.primaryThresholdMet ? "check" : "close"} size={14} />
            {t("首要任务等级 ≥ 2")}
          </span>
          <span className={cn("inline-flex items-center gap-1", breakdown.scoreThresholdMet ? "text-success" : "text-error")}>
            <Icon name={breakdown.scoreThresholdMet ? "check" : "close"} size={14} />
            {t("加权总分 ≥ 50")}
          </span>
        </div>
      </div>

      <div className="border-t border-outline-variant pt-3">
        <p className="text-label font-semibold">{t("总分计算明细")}</p>
        <div className="mt-2 flex flex-col gap-1">
          {breakdown.rows.map((row) => (
            <div key={row.taskId} className="flex items-baseline gap-2 text-label text-on-surface-variant">
              <span className="w-9 shrink-0 text-center font-mono text-on-surface">L{row.level}</span>
              <span className="min-w-0 flex-1 truncate">{row.title}</span>
              <span className="shrink-0 tabular-nums">
                {(row.level / 4).toFixed(2)}×100×{row.coefficient}
                <span className="text-on-surface"> = {Math.round(row.weighted)}</span>
              </span>
            </div>
          ))}
          <div className="flex items-baseline gap-2 border-t border-outline-variant pt-1 text-label">
            <span className="w-9 shrink-0" />
            <span className="flex-1">{t("Σ(单项 × 系数) ÷ Σ系数")}</span>
            <span className="shrink-0 font-medium tabular-nums text-on-surface">{breakdown.total.toFixed(1)}</span>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        {tasks.map((task) => {
          const cardTaskMeta = cardTask(task.task_id);
          return (
            <details key={task.task_id} className="border-t border-outline-variant pt-2" open={(task.level || 0) < 2}>
              <summary className="flex cursor-pointer list-none items-center gap-2">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-outline-variant font-mono text-label tabular-nums">{task.level ?? 0}</span>
                <span className="min-w-0 flex-1 truncate text-body-sm font-medium">{cardTaskMeta?.title || task.task_id}</span>
                {cardTaskMeta && (
                  <span className="shrink-0 text-[11px] text-on-surface-variant">
                    {t(IMPORTANCE_LABEL[cardTaskMeta.importance] || cardTaskMeta.importance)}
                  </span>
                )}
                <span className="shrink-0 text-label text-on-surface-variant">{confidenceLabel(task.confidence, t)}</span>
              </summary>
              <p className="mt-2 text-body-sm text-on-surface-variant">{task.reasoning_summary || t("暂无推理摘要")}</p>
              {task.transfer_boundary && (
                <p className="mt-1.5 rounded-md bg-surface-low px-2.5 py-1.5 text-label text-on-surface-variant">
                  <span className="font-medium text-on-surface">{t("迁移边界")}</span>{task.transfer_boundary}
                </p>
              )}
              {!!task.evidence?.length && (
                <div className="mt-2 flex flex-col gap-1.5">
                  {task.evidence.map((evidence, index) => (
                    <EvidenceQuote key={`${evidence.quote}-${index}`} evidence={evidence} />
                  ))}
                </div>
              )}
              {!!task.risks?.length && (
                <div className="mt-2">
                  <p className="text-label font-semibold">{t("能力缺口")}</p>
                  <ul className="mt-1 list-disc space-y-1 pl-4 text-label text-on-surface-variant">
                    {task.risks.map((risk) => <li key={risk}>{risk}</li>)}
                  </ul>
                </div>
              )}
            </details>
          );
        })}
      </div>

      {!!assessment.review_corrections.length && (
        <div className="border-t border-outline-variant pt-3">
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

      {assessment.decision === "interview" && !!focusByTask.size && (
        <div className="border-t border-outline-variant pt-3">
          <p className="text-label font-semibold">{t("针对性面试重点")}</p>
          <ul className="mt-2 list-disc space-y-1 pl-4 text-label text-on-surface-variant">
            {[...focusByTask.entries()].map(([taskId, focus]) => (
              <li key={taskId}>
                <span className="font-medium text-on-surface">{cardTask(taskId)?.title || taskId}</span>
                {focus ? `：${focus}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="border-t border-outline-variant pt-3">
        <p className="text-label font-semibold">{t("模型与降级")}</p>
        <p className="mt-1 text-label text-on-surface-variant">
          {models.join(" · ") || "—"}
          {!!degradedCount && (
            <span className="ml-2 inline-flex items-center gap-1 text-warning">
              <Icon name="alert-triangle" size={13} />
              {t("{n} 次节点降级", { n: degradedCount })}
            </span>
          )}
        </p>
        {run?.error_message && (
          <p className="mt-2 rounded-md bg-error-container p-3 text-body-sm text-on-error-container">{run.error_message}</p>
        )}
      </div>
    </section>
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
    <div className="rounded-md bg-surface-low px-2.5 py-2">
      <span className={cn("inline-flex h-5 items-center rounded-full px-2 text-[10px] font-medium", meta.className)}>{meta.label}</span>
      <q className="mt-1.5 block text-label text-on-surface">{evidence.quote || t("未提供引用")}</q>
      {evidence.relevance && <p className="mt-1 text-[11px] leading-4 text-on-surface-variant">{evidence.relevance}</p>}
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
