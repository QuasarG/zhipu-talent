import { useMemo } from "react";
import type {
  CandidateBrief,
  CandidateDetail,
  InterviewAssessment,
  InterviewAssessmentBatch,
  InterviewAssessmentRun,
  JdEntry,
} from "@/lib/types";
import type { AdmissionGraphNode } from "@/features/admission/AdmissionWorkflowGraph";
import AdmissionWorkflowGraph from "@/features/admission/AdmissionWorkflowGraph";
import AdmissionReport, { NodeInspector } from "./AdmissionReport";
import { BatchRunView, NewBatchPanel } from "./BatchViews";
import EmptyState from "./EmptyState";
import ResumeContent from "@/features/resume/ResumeContent";
import Card from "@/components/ui/Card";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import { useI18n } from "@/lib/i18n";

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
  candidateDetail,
  candidateDetailLoading,
  selectedNode,
  selectedNodeId,
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
  onSelectNode,

  onCancelRun,

  onExitCreate,
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
  candidateDetail: CandidateDetail | null;
  candidateDetailLoading: boolean;
  selectedNode: AdmissionGraphNode | null;
  selectedNodeId: string | null;
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
  onSelectNode: (node: AdmissionGraphNode) => void;
  onCancelRun: (runId: string) => void;
  onExitCreate: () => void;
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
        candidates={candidates}
        jds={allJds}
        assessments={assessments}
        candidateDetail={candidateDetail}
        candidateDetailLoading={candidateDetailLoading}
        onCandidateReviewed={onCandidateReviewed}
        selectedNode={selectedNode}
        selectedNodeId={selectedNodeId}
        onSelectNode={onSelectNode}
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
        onExit={onExitCreate}
      />
    );
  }

  if (selectedCandidateId && selectedJdId) {
    return (
      <PairReportView
        assessments={assessments}
        allJds={allJds}
        candidates={candidates}
        candidateId={selectedCandidateId}
        jdId={selectedJdId}
        selectedNode={selectedNode}
        selectedNodeId={selectedNodeId}
        onSelectNode={onSelectNode}
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
          <ResumeContent key={candidateDetail.id} detail={candidateDetail} onReviewed={onCandidateReviewed} />
        ) : (
          <EmptyState
            icon="person"
            title={t("从左侧选择一个候选人")}
            hint={t("选中候选人根节点查看简历；选择岗位子项查看该配对的准入报告")}
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

/** 候选人–JD 配对的当前报告视图：真实运行图 + 完整报告与节点详情 */
function PairReportView({
  assessments,
  allJds,
  candidates,
  candidateId,
  jdId,
  selectedNode,
  selectedNodeId,
  onSelectNode,
}: {
  assessments: InterviewAssessment[];
  allJds: JdEntry[];
  candidates: CandidateBrief[];
  candidateId: string;
  jdId: string;
  selectedNode: AdmissionGraphNode | null;
  selectedNodeId: string | null;
  onSelectNode: (node: AdmissionGraphNode) => void;
}) {
  const { t } = useI18n();
  const assessment = assessments.find(
    (item) => item.candidate_id === candidateId && item.jd_id === jdId,
  );
  const jd = allJds.find((item) => item.id === jdId);
  const candidate = candidates.find((item) => item.id === candidateId);

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

  // 已保存报告的运行轨迹回放为只读运行图
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

  const graphCandidate = candidate
    ?? (assessment.candidate_name
      ? ({
          id: assessment.candidate_id,
          name: assessment.candidate_name,
          role: "",
          stage: "",
          group: "",
          level: "",
          category: "",
          engagement_status: "",
          admitted_at: null,
        } as CandidateBrief)
      : undefined);
  const graphJd = jd
    ?? (assessment.jd_title
      ? ({
          id: assessment.jd_id,
          title: assessment.jd_title,
          team: "",
          raw_text: "",
          supplements: [],
          assessment_card: null,
          card_status: "ready",
          card_error: "",
          card_run_trace: [],
          card_model_usage: [],
          archived: false,
          created_at: "",
          updated_at: "",
        } as JdEntry)
      : undefined);

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
          <div className="my-5 border-t border-outline-variant" />
          <NodeInspector node={selectedNode} />
        </div>
      </Card>

      {/* 报告生成时的真实调用链：佐证材料，占辅列 */}
      <Card variant="filled" className="relative min-h-[360px] overflow-hidden flex flex-col">
        <div className="flex items-center gap-3 border-b border-outline-variant px-4 py-3 shrink-0">
          <div className="min-w-0">
            <p className="truncate text-title">{t("运行过程")}</p>
            <p className="mt-0.5 truncate text-label text-on-surface-variant">
              {t("报告生成时的真实调用链")}
            </p>
          </div>
        </div>
        <div className="flex-1 min-h-0 overflow-auto admission-panel-scrollbar">
          <AdmissionWorkflowGraph
            run={reportRun}
            candidate={graphCandidate}
            jd={graphJd}
            selectedNodeId={selectedNodeId}
            onSelectNode={onSelectNode}
          />
        </div>
      </Card>
    </div>
  );
}
