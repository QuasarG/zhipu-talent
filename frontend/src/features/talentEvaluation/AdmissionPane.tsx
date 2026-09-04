import { useMemo } from "react";
import type {
  CandidateBrief,
  CandidateDetail,
  InterviewAssessment,
  InterviewAssessmentBatch,
  InterviewAssessmentRun,
  JdEntry,
} from "@/lib/types";
import EvaluationAgentTimeline from "@/features/admission/EvaluationAgentTimeline";
import AdmissionReport from "./AdmissionReport";
import { BatchRunView, NewBatchPanel } from "./BatchViews";
import EmptyState from "./EmptyState";
import ResumeContent from "@/features/resume/ResumeContent";
import Card from "@/components/ui/Card";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import { useI18n } from "@/lib/i18n";
import type { CandidateRecordView } from "@/features/resume/ResumeContent";

const TERMINAL_BATCH_STATUSES = new Set(["completed", "failed", "cancelled"]);

/**
 * 面试准入子界面的内容区（docs/rebuild.md §3）。
 * 优先级：运行中的批次 → 新建批次临时模式 → 配对报告 → 候选人档案摘要 → 空态。
 */
export default function AdmissionPane({
  creating,
  batch,
  candidates,
  allJds,
  assessments,
  activeRuns,
  selectedCandidateId,
  selectedJdId,
  selectedCandidateView,
  candidateDetail,
  candidateDetailLoading,
  activeRunId,
  draftCandidateIds,
  draftJdIds,
  draftCandidateSearch,
  draftJdSearch,
  starting,
  onCandidateReviewed,
  onDraftCandidateIds,
  onDraftJdIds,
  onDraftCandidateSearch,
  onDraftJdSearch,
  onCancelRun,

  onStartBatch,
}: {
  creating: boolean;
  batch: InterviewAssessmentBatch | null;
  candidates: CandidateBrief[];
  allJds: JdEntry[];
  assessments: InterviewAssessment[];
  activeRuns: InterviewAssessmentRun[];
  selectedCandidateId: string | null;
  selectedJdId: string | null;
  selectedCandidateView: CandidateRecordView;
  candidateDetail: CandidateDetail | null;
  candidateDetailLoading: boolean;
  activeRunId: string | null;
  draftCandidateIds: Set<string>;
  draftJdIds: Set<string>;
  draftCandidateSearch: string;
  draftJdSearch: string;
  starting: boolean;
  /** 简历卡片内的人工裁决等操作完成后，静默刷新候选人详情 */
  onCandidateReviewed: () => void;
  onDraftCandidateIds: (value: Set<string>) => void;
  onDraftJdIds: (value: Set<string>) => void;
  onDraftCandidateSearch: (value: string) => void;
  onDraftJdSearch: (value: string) => void;
  onCancelRun: (runId: string) => void;
  onStartBatch: (
    pairs: Array<{ candidate_id: string; jd_id: string }>,
    requestId: string,
    forceReason: string,
  ) => Promise<void>;
}) {
  const { t } = useI18n();
  const readyJds = useMemo(
    () => allJds.filter((jd) => !jd.archived && jd.card_status === "ready"),
    [allJds],
  );

  // 评估态不再霸屏：用户在左树显式选择了候选人/配对时优先显示选中内容，
  // 批次运行视图由左栏队列卡承载（点选队列行也可切回）
  if (batch && !TERMINAL_BATCH_STATUSES.has(batch.status)
    && !selectedCandidateId && !selectedJdId && !creating) {
    return (
      <BatchRunView
        batch={batch}
        activeRunId={activeRunId}
        jds={allJds}
        assessments={assessments}
        candidateDetail={candidateDetail}
        candidateDetailLoading={candidateDetailLoading}
        onCandidateReviewed={onCandidateReviewed}
        onCancelRun={onCancelRun}
      />
    );
  }

  if (creating) {
    return (
      <NewBatchPanel
        candidates={candidates}
        jds={readyJds}
        assessments={assessments}
        activeRuns={activeRuns}
        candidateIds={draftCandidateIds}
        jdIds={draftJdIds}
        candidateSearch={draftCandidateSearch}
        jdSearch={draftJdSearch}
        onCandidateSearch={onDraftCandidateSearch}
        onJdSearch={onDraftJdSearch}
        onCandidateIds={onDraftCandidateIds}
        onJdIds={onDraftJdIds}
        starting={starting}
        onStart={onStartBatch}
      />
    );
  }

  if (selectedCandidateId && selectedJdId) {
    return (
      <PairReportView
        assessments={assessments}
        allJds={allJds}
        candidateId={selectedCandidateId}
        jdId={selectedJdId}
      />
    );
  }

  if (selectedCandidateId) {
    // 候选人根节点：直接展示"结构化简历 / 简历原件"卡片，不再跳转人才档案
    return (
      <Card variant="filled" className="min-h-0 flex-1 overflow-hidden p-5">
        {candidateDetailLoading && !candidateDetail ? (
          <div className="flex h-full items-center justify-center">
            <LoadingIndicator size={32} label={t("加载中…")} />
          </div>
        ) : candidateDetail ? (
          <ResumeContent
            key={candidateDetail.id}
            detail={candidateDetail}
            onReviewed={onCandidateReviewed}
            hideTabs
            view={selectedCandidateView}
          />
        ) : (
          <EmptyState
            icon="person"
            title={t("从左侧选择一个候选人")}
            hint={t("展开候选人目录，先查看原始材料，再进入结构化简历或岗位评估")}
          />
        )}
      </Card>
    );
  }

  return (
    <Card variant="filled" className="min-h-0 flex-1 overflow-hidden flex flex-col">
      <EmptyState
        icon="fact_check"
        title={t("选择左侧文件夹中的岗位子项")}
        hint={t("每个岗位子项对应一次候选人–JD 准入评估，进入或不进入面试都保留完整报告")}
      />
    </Card>
  );
}

/** 候选人–JD 配对的当前报告视图：完整报告 + 双 Agent 活动回放。 */
function PairReportView({
  assessments,
  allJds,
  candidateId,
  jdId,
}: {
  assessments: InterviewAssessment[];
  allJds: JdEntry[];
  candidateId: string;
  jdId: string;
}) {
  const { t } = useI18n();
  const assessment = assessments.find(
    (item) => item.candidate_id === candidateId && item.jd_id === jdId,
  );
  const jd = allJds.find((item) => item.id === jdId);

  if (!assessment) {
    return (
      <Card variant="filled" className="min-h-0 overflow-hidden">
        <EmptyState
          icon="fact_check"
          title={t("该配对还没有当前报告")}
          hint={t("可以在此配对上发起准入评估，或等待正在运行的评估完成")}
        />
      </Card>
    );
  }

  // 已保存报告与运行中批次共用同一活动流组件，仅切换为只读状态。
  const reportRun = {
    id: assessment.id,
    batch_id: "saved-reports",
    candidate_id: assessment.candidate_id,
    candidate_name: assessment.candidate_name,
    jd_id: assessment.jd_id,
    jd_title: assessment.jd_title,
    status: "completed" as const,
    current_node: assessment.run_trace.at(-1)?.node_id || "admission_decision",
    run_trace: assessment.run_trace,
    model_usage: assessment.model_usage,
    error_message: "",
    cancellation_requested: false,
  };

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-3 xl:grid-cols-[minmax(560px,1.7fr)_minmax(360px,1fr)]">
      {/* 报告是交付物：占主列 */}
      <Card variant="filled" className="min-h-[420px] overflow-hidden flex flex-col">
        <div className="border-b border-outline-variant px-4 py-3 shrink-0">
          <p className="text-title">
            {assessment.candidate_name || t("候选人")} × {assessment.jd_title || jd?.title || t("岗位")}
          </p>
          <p className="mt-0.5 text-label text-on-surface-variant">{t("评估结论与证据")}</p>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto p-5 admission-panel-scrollbar">
          <AdmissionReport assessment={assessment} jd={jd} />
        </div>
      </Card>

      {/* 同一条真实活动流可在运行中观看，也可在历史报告中回放。 */}
      <Card variant="filled" className="relative min-h-[360px] overflow-hidden flex flex-col">
        <EvaluationAgentTimeline run={reportRun} />
      </Card>
    </div>
  );
}
