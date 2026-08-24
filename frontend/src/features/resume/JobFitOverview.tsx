import { useState } from "react";
import Icon from "@/components/ui/Icon";
import Progress from "@/components/ui/Progress";
import { StatusChip } from "@/components/ui/Chip";
import { cn } from "@/lib/cn";
import type {
  Evaluation,
  InterviewDecision,
  JobFitAssessment,
  JobFitFinding,
  JobRequirementAssessment,
} from "@/lib/types";
import { useI18n } from "@/lib/i18n";


interface Props {
  evaluation: Evaluation;
  shareState: "idle" | "working" | "done" | "error";
  canShare: boolean;
  onShare: () => void;
}

const DECISIONS: Record<InterviewDecision, {
  label: string;
  tone: "success" | "warning" | "error";
  icon: string;
  rail: string;
}> = {
  interview: { label: "进入面试", tone: "success", icon: "how_to_reg", rail: "bg-success" },
  hold: { label: "待补信息", tone: "warning", icon: "pending_actions", rail: "bg-warning" },
  reject: { label: "不进入面试", tone: "error", icon: "person_remove", rail: "bg-error" },
};

const REQUIREMENTS: Record<JobRequirementAssessment["status"], {
  label: string;
  icon: string;
  className: string;
}> = {
  met: { label: "满足", icon: "check_circle", className: "text-success" },
  unknown: { label: "待确认", icon: "help", className: "text-warning" },
  unmet: { label: "不满足", icon: "cancel", className: "text-error" },
};


export default function JobFitOverview({ evaluation, shareState, canShare, onShare }: Props) {
  const { t } = useI18n();
  const assessments = evaluation.job_fit_assessments || [];
  const best = assessments.find((item) => item.jd_id === evaluation.best_fit_jd_id) || assessments[0];
  const decision = DECISIONS[best?.decision || "hold"];

  return (
    <div>
      <header className="pb-5 border-b-2 border-outline-variant">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 max-w-3xl">
            <div className="flex flex-wrap items-center gap-2">
              <StatusChip tone={decision.tone} variant="filled" icon={decision.icon}>
                {t(decision.label)}
              </StatusChip>
              <span className="text-label font-semibold text-on-surface-variant">
                {t("最匹配：{job}", { job: evaluation.best_fit_jd_title || best?.jd_title || "—" })}
              </span>
            </div>
            <h2 className="mt-3 text-headline font-bold text-on-surface">{t("面试准入建议")}</h2>
            <p className="mt-1 text-body font-medium leading-6 text-on-surface">
              {evaluation.decision_summary || best?.decision_reason || t("暂无准入结论")}
            </p>
            <p className="mt-1 text-label text-on-surface-variant">
              {t("每个 JD 独立判断；进入面试表示值得进一步验证，不代表录用")}
            </p>
          </div>
          <button
            onClick={onShare}
            disabled={!canShare || shareState === "working"}
            className="state-layer inline-flex items-center gap-1.5 h-8 px-3 rounded-full text-label font-medium text-primary border border-outline-variant cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Icon name={shareState === "done" ? "check" : "share"} size={14} />
            {shareState === "done" ? t("已复制链接") : shareState === "working" ? t("生成中…") : shareState === "error" ? t("分享失败") : t("分享")}
          </button>
        </div>
      </header>

      <section className="py-5">
        <div className="flex items-end justify-between gap-3 mb-3">
          <div>
            <p className="text-label font-bold tracking-wide text-primary">JD × RESUME</p>
            <h3 className="mt-0.5 text-title-lg font-bold text-on-surface">{t("逐岗位准入结论")}</h3>
          </div>
          <span className="text-label text-on-surface-variant">{t("{n} 个岗位", { n: assessments.length })}</span>
        </div>
        <div className="space-y-3">
          {assessments.map((assessment, index) => (
            <AssessmentCard
              key={assessment.jd_id}
              assessment={assessment}
              index={index}
              initiallyOpen={assessment.jd_id === best?.jd_id}
            />
          ))}
        </div>
      </section>
    </div>
  );
}


function AssessmentCard({ assessment, index, initiallyOpen }: {
  assessment: JobFitAssessment;
  index: number;
  initiallyOpen: boolean;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(initiallyOpen);
  const decision = DECISIONS[assessment.decision];

  return (
    <article className="relative overflow-hidden rounded-md border border-outline-variant bg-surface-lowest shadow-sm">
      <span className={cn("absolute inset-y-0 left-0 w-1", decision.rail)} aria-hidden="true" />
      <button
        type="button"
        className="state-layer grid w-full grid-cols-[32px_minmax(0,1fr)_auto_24px] items-center gap-3 py-3.5 pl-4 pr-3 text-left"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="flex h-8 w-8 items-center justify-center rounded-sm bg-surface-high text-label font-bold tabular-nums text-on-surface-variant">
          {String(index + 1).padStart(2, "0")}
        </span>
        <span className="min-w-0">
          <span className="block truncate text-title font-bold text-on-surface">{assessment.jd_title}</span>
          <span className="mt-0.5 block line-clamp-1 text-label text-on-surface-variant">{assessment.decision_reason}</span>
        </span>
        <span className="flex items-center gap-3">
          <span className="hidden text-right sm:block">
            <span className="block text-title font-bold tabular-nums text-on-surface">{assessment.fit_score}</span>
            <span className="block text-label text-on-surface-variant">{t("岗位匹配")}</span>
          </span>
          <StatusChip tone={decision.tone} variant="filled" icon={decision.icon}>{t(decision.label)}</StatusChip>
        </span>
        <Icon name="expand_more" size={20} className={cn("text-on-surface-variant transition-transform", open && "rotate-180")} />
      </button>

      <div className="process-collapse" data-open={open}>
        <div>
          <div className="border-t border-outline-variant px-4 pb-5 pt-4 sm:pl-16">
            <p className="text-body-sm font-medium leading-5 text-on-surface">{assessment.decision_reason}</p>
            <div className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(260px,0.75fr)]">
              <div className="space-y-5">
                <section>
                  <SectionTitle icon="rule" title={t("硬门槛")} />
                  {assessment.hard_requirements.length ? (
                    <div className="mt-2 divide-y divide-outline-variant rounded-sm border border-outline-variant">
                      {assessment.hard_requirements.map((item, requirementIndex) => (
                        <RequirementRow key={`${item.requirement}-${requirementIndex}`} item={item} />
                      ))}
                    </div>
                  ) : (
                    <p className="mt-2 text-body-sm text-on-surface-variant">{t("JD 未声明可机器核对的硬门槛")}</p>
                  )}
                </section>

                <section>
                  <SectionTitle icon="analytics" title={t("岗位匹配维度")} />
                  <div className="mt-3 space-y-3">
                    {assessment.dimensions.map((dimension) => (
                      <div key={dimension.key} className="grid grid-cols-[120px_minmax(0,1fr)_48px] items-start gap-3">
                        <span className="text-body-sm font-semibold text-on-surface">{dimension.label}</span>
                        <div>
                          <Progress value={dimension.score * 20} />
                          <p className="mt-1 text-label leading-4 text-on-surface-variant">{dimension.rationale}</p>
                        </div>
                        <span className="text-right text-body-sm font-bold tabular-nums text-on-surface">{dimension.score.toFixed(1)}</span>
                      </div>
                    ))}
                  </div>
                </section>
              </div>

              <aside className="space-y-4">
                <FindingBlock icon="workspace_premium" title={t("直接优势")} tone="text-success" findings={assessment.strengths} />
                <FindingBlock icon="warning" title={t("风险与缺口")} tone="text-error" findings={assessment.risks} extras={assessment.missing_information} />
                {!!assessment.interview_questions.length && (
                  <section>
                    <SectionTitle icon="quiz" title={t("面试验证问题")} />
                    <ol className="mt-2 space-y-2">
                      {assessment.interview_questions.map((question, questionIndex) => (
                        <li key={questionIndex} className="grid grid-cols-[20px_minmax(0,1fr)] gap-2 text-body-sm leading-5 text-on-surface">
                          <span className="font-bold tabular-nums text-primary">{String(questionIndex + 1).padStart(2, "0")}</span>
                          <span>{question}</span>
                        </li>
                      ))}
                    </ol>
                  </section>
                )}
              </aside>
            </div>
          </div>
        </div>
      </div>
    </article>
  );
}


function RequirementRow({ item }: { item: JobRequirementAssessment }) {
  const { t } = useI18n();
  const meta = REQUIREMENTS[item.status];
  return (
    <div className="grid grid-cols-[20px_minmax(0,1fr)_auto] items-start gap-2 px-3 py-2.5">
      <Icon name={meta.icon} size={17} fill className={cn("mt-0.5", meta.className)} />
      <div>
        <p className="text-body-sm font-semibold text-on-surface">{item.requirement}</p>
        <p className="mt-0.5 text-label leading-4 text-on-surface-variant">{item.rationale}</p>
        {!!item.evidence.length && <EvidenceQuotes quotes={item.evidence} />}
      </div>
      <span className={cn("text-label font-bold", meta.className)}>{t(meta.label)}</span>
    </div>
  );
}


function FindingBlock({ icon, title, tone, findings, extras = [] }: {
  icon: string;
  title: string;
  tone: string;
  findings: JobFitFinding[];
  extras?: string[];
}) {
  if (!findings.length && !extras.length) return null;
  return (
    <section>
      <SectionTitle icon={icon} title={title} className={tone} />
      <div className="mt-2 space-y-2">
        {findings.map((finding, index) => (
          <div key={index} className="text-body-sm leading-5 text-on-surface">
            <p>{finding.summary}</p>
            {!!finding.evidence.length && <EvidenceQuotes quotes={finding.evidence} />}
          </div>
        ))}
        {extras.map((item, index) => <p key={`extra-${index}`} className="text-body-sm leading-5 text-on-surface">{item}</p>)}
      </div>
    </section>
  );
}


function EvidenceQuotes({ quotes }: { quotes: string[] }) {
  return (
    <div className="mt-1 space-y-1">
      {quotes.map((quote, index) => (
        <blockquote key={index} className="border-l-2 border-outline-variant pl-2 text-label leading-4 text-on-surface-variant">
          “{quote}”
        </blockquote>
      ))}
    </div>
  );
}


function SectionTitle({ icon, title, className }: { icon: string; title: string; className?: string }) {
  return (
    <div className={cn("flex items-center gap-1.5 text-on-surface", className)}>
      <Icon name={icon} size={17} />
      <h4 className="text-body font-bold">{title}</h4>
    </div>
  );
}
