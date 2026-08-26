import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type {
  CandidateBrief,
  InterviewAssessment,
  InterviewAssessmentBatch,
  InterviewAssessmentRun,
  JdEntry,
} from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import Card from "@/components/ui/Card";
import Button, { IconButton } from "@/components/ui/Button";
import Icon from "@/components/ui/Icon";
import { StatusChip } from "@/components/ui/Chip";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import SearchField from "@/components/ui/SearchField";
import Progress from "@/components/ui/Progress";
import AdmissionWorkflowGraph, {
  type AdmissionGraphNode,
} from "@/features/admission/AdmissionWorkflowGraph";
import { cn } from "@/lib/cn";
import { useSessionState } from "@/lib/sessionState";
import { useI18n } from "@/lib/i18n";

const TERMINAL_BATCH_STATUSES = new Set(["completed", "failed", "cancelled"]);
const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "cancelled"]);

const RUN_STATUS_LABEL: Record<string, string> = {
  queued: "排队中",
  running: "评估中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已停止",
};

const RUN_STATUS_TONE: Record<string, "primary" | "success" | "error" | "neutral"> = {
  queued: "neutral",
  running: "primary",
  completed: "success",
  failed: "error",
  cancelled: "neutral",
};

interface EvidenceView {
  quote?: string;
  evidence_type?: "direct" | "transferable" | "background";
  confidence?: "high" | "medium" | "low";
  relevance?: string;
}

interface TaskAssessmentView {
  task_id?: string;
  level?: number;
  confidence?: "high" | "medium" | "low";
  reasoning_summary?: string;
  transfer_boundary?: string;
  evidence?: EvidenceView[];
  risks?: string[];
}

type Translate = ReturnType<typeof useI18n>["t"];

function assessmentToRun(assessment: InterviewAssessment): InterviewAssessmentRun {
  return {
    id: assessment.id,
    batch_id: "saved-reports",
    candidate_id: assessment.candidate_id,
    jd_id: assessment.jd_id,
    status: "completed",
    current_node: assessment.run_trace.at(-1)?.node_id || "admission_decision",
    run_trace: assessment.run_trace,
    model_usage: assessment.model_usage,
    error_message: "",
    cancellation_requested: false,
  };
}

function assessmentsToBatch(assessments: InterviewAssessment[]): InterviewAssessmentBatch {
  const updatedAt = assessments[0]?.updated_at || new Date().toISOString();
  return {
    id: "saved-reports",
    status: "completed",
    candidate_ids: [...new Set(assessments.map((item) => item.candidate_id))],
    jd_ids: [...new Set(assessments.map((item) => item.jd_id))],
    total_pairs: assessments.length,
    completed_pairs: assessments.length,
    failed_pairs: 0,
    cancelled_pairs: 0,
    created_at: updatedAt,
    started_at: updatedAt,
    completed_at: updatedAt,
    runs: assessments.map(assessmentToRun),
  };
}

export default function InterviewAdmission() {
  const [candidates, setCandidates] = useState<CandidateBrief[]>([]);
  const [jds, setJds] = useState<JdEntry[]>([]);
  const [candidateIdList, setCandidateIdList] = useSessionState<string[]>("interview-admission.candidate-ids", []);
  const [jdIdList, setJdIdList] = useSessionState<string[]>("interview-admission.jd-ids", []);
  const [candidateSearch, setCandidateSearch] = useSessionState("interview-admission.candidate-search", "");
  const [jdSearch, setJdSearch] = useSessionState("interview-admission.jd-search", "");
  const [batchId, setBatchId] = useSessionState<string | null>("interview-admission.batch-id", null);
  const [activeRunId, setActiveRunId] = useSessionState<string | null>("interview-admission.active-run-id", null);
  const [reportAssessmentId, setReportAssessmentId] = useSessionState<string | null>("interview-admission.report-id", null);
  const [selectedNodeId, setSelectedNodeId] = useSessionState<string | null>("interview-admission.node-id", null);
  const [batch, setBatch] = useState<InterviewAssessmentBatch | null>(null);
  const [assessments, setAssessments] = useState<InterviewAssessment[]>([]);
  const [selectedNode, setSelectedNode] = useState<AdmissionGraphNode | null>(null);
  const [forceAllowed, setForceAllowed] = useState(false);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const [restoring, setRestoring] = useState(!!batchId);
  const { t } = useI18n();
  const force = forceAllowed;

  const candidateIds = useMemo(() => new Set(candidateIdList), [candidateIdList]);
  const jdIds = useMemo(() => new Set(jdIdList), [jdIdList]);
  const selectedExistingAssessments = useMemo(() => assessments.filter((item) => (
    item.is_valid && candidateIds.has(item.candidate_id) && jdIds.has(item.jd_id)
  )), [assessments, candidateIds, jdIds]);
  const reportAssessment = assessments.find((item) => item.id === reportAssessmentId);
  const reportBatch = useMemo(() => assessmentsToBatch(assessments), [assessments]);
  const reportRun = reportAssessment ? assessmentToRun(reportAssessment) : undefined;

  const updateCandidateIds = useCallback((next: Set<string>) => setCandidateIdList([...next]), [setCandidateIdList]);
  const updateJdIds = useCallback((next: Set<string>) => setJdIdList([...next]), [setJdIdList]);

  const loadInputs = useCallback(async () => {
    const [candidateRows, jdRows, settings, assessmentRows] = await Promise.all([
      api.candidates.list(),
      api.jds.list(),
      api.interviewAssessments.settings(),
      api.interviewAssessments.list(),
    ]);
    const readyJds = jdRows.filter((jd) => !jd.archived && jd.card_status === "ready");
    setCandidates(candidateRows);
    setJds(readyJds);
    setAssessments(assessmentRows);
    setForceAllowed(settings.can_manage_force_reevaluation && settings.allow_force_reevaluation);
    setCandidateIdList((current) => current.filter((id) => candidateRows.some((candidate) => candidate.id === id)));
    setJdIdList((current) => current.filter((id) => readyJds.some((jd) => jd.id === id)));
  }, [setCandidateIdList, setJdIdList]);

  const hydrateBatch = useCallback(async (id: string) => {
    try {
      const next = await api.interviewAssessments.batch(id);
      setBatch(next);
      setActiveRunId((current) => current && next.runs?.some((run) => run.id === current) ? current : next.runs?.[0]?.id || null);
      if (TERMINAL_BATCH_STATUSES.has(next.status)) {
        setAssessments(await api.interviewAssessments.list());
      }
      setError("");
      return next;
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : t("恢复评估批次失败");
      if (message.includes("不存在") || message.includes("404")) {
        setBatchId(null);
        setBatch(null);
        setActiveRunId(null);
      }
      setError(message);
      return null;
    } finally {
      setRestoring(false);
    }
  }, [setActiveRunId, setBatchId, t]);

  useEffect(() => {
    loadInputs().catch((reason) => setError(reason instanceof Error ? reason.message : t("加载失败")));
  }, [loadInputs, t]);

  useEffect(() => {
    if (!batchId) {
      setRestoring(false);
      return;
    }
    void hydrateBatch(batchId);
  }, [batchId, hydrateBatch]);

  useEffect(() => {
    if (!batch || TERMINAL_BATCH_STATUSES.has(batch.status)) return;
    const timer = window.setInterval(() => void hydrateBatch(batch.id), 1200);
    return () => window.clearInterval(timer);
  }, [batch, hydrateBatch]);

  useEffect(() => {
    if (!batchId) return;
    const refresh = () => {
      if (document.visibilityState === "visible") void hydrateBatch(batchId);
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [batchId, hydrateBatch]);

  const start = async () => {
    if (!candidateIds.size || !jdIds.size || starting) return;
    if (!force && selectedExistingAssessments.length) {
      setReportAssessmentId(selectedExistingAssessments[0].id);
      setSelectedNode(null);
      setSelectedNodeId(null);
      setError("");
      return;
    }
    setStarting(true);
    setError("");
    try {
      const next = await api.interviewAssessments.start([...candidateIds], [...jdIds], force);
      setBatch(next);
      setBatchId(next.id);
      setActiveRunId(next.runs?.[0]?.id || null);
      setSelectedNodeId(null);
      setSelectedNode(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("启动失败"));
    } finally {
      setStarting(false);
    }
  };

  const resetBatch = () => {
    setBatchId(null);
    setBatch(null);
    setActiveRunId(null);
    setSelectedNodeId(null);
    setSelectedNode(null);
    setError("");
  };

  const activeRun = batch?.runs?.find((run) => run.id === activeRunId) ?? batch?.runs?.[0];
  const activeAssessment = activeRun?.status === "completed"
    ? assessments.find((item) => item.candidate_id === activeRun.candidate_id && item.jd_id === activeRun.jd_id)
    : undefined;
  const running = !!batch && !TERMINAL_BATCH_STATUSES.has(batch.status);
  const pairCount = candidateIds.size * jdIds.size;

  const selectGraphNode = useCallback((node: AdmissionGraphNode) => {
    setSelectedNode(node);
    setSelectedNodeId(node.id);
  }, [setSelectedNodeId]);

  const openReport = useCallback((id: string) => {
    setReportAssessmentId(id);
    setSelectedNode(null);
    setSelectedNodeId(null);
    setError("");
  }, [setReportAssessmentId, setSelectedNodeId]);

  const closeReport = useCallback(() => {
    setReportAssessmentId(null);
    setSelectedNode(null);
    setSelectedNodeId(null);
  }, [setReportAssessmentId, setSelectedNodeId]);

  return (
    <div className="w-full max-w-full min-w-0">
      <PageToolbar
        title={t("面试准入评估")}
        subtitle={t("围绕岗位核心任务，用可追溯证据决定是否投入面试资源")}
        center={reportAssessment ? (
          <ReportSummary assessments={assessments} />
        ) : batch ? (
          <BatchSummary batch={batch} />
        ) : (
          <div className="hidden xl:flex items-center gap-3 text-label text-on-surface-variant">
            <span>{t("{n} 位候选人", { n: candidateIds.size })}</span>
            <span className="w-6 border-t border-outline-variant" />
            <span>{t("{n} 个岗位", { n: jdIds.size })}</span>
            <span className="w-6 border-t border-outline-variant" />
            <span>{t("{n} 个评估配对", { n: pairCount })}</span>
          </div>
        )}
        right={reportAssessment ? (
          <Button variant="tonal" icon="arrow_back" onClick={closeReport}>{t("返回配对选择")}</Button>
        ) : batch ? (
          running ? (
            <Button
              variant="tonal"
              icon="stop_circle"
              onClick={async () => {
                await api.interviewAssessments.cancelBatch(batch.id);
                await hydrateBatch(batch.id);
              }}
            >
              {t("停止整批")}
            </Button>
          ) : (
            <Button variant="tonal" icon="add" onClick={resetBatch}>{t("新建评估批次")}</Button>
          )
        ) : (
          <>
            {!!assessments.length && (
              <Button variant="outlined" icon="description" onClick={() => openReport(assessments[0].id)}>
                {t("已有报告 {n}", { n: assessments.length })}
              </Button>
            )}
            <Button
              variant="filled"
              icon={selectedExistingAssessments.length && !force ? "description" : "play_arrow"}
              disabled={!pairCount || starting}
              onClick={selectedExistingAssessments.length && !force ? () => openReport(selectedExistingAssessments[0].id) : start}
            >
              {starting
                ? t("启动中…")
                : selectedExistingAssessments.length && !force
                  ? t("查看已有报告 {n}", { n: selectedExistingAssessments.length })
                  : t("开始 {n} 个配对", { n: pairCount })}
            </Button>
          </>
        )}
      />

      {error && (
        <div className="mx-2 mb-3 flex items-center gap-2 rounded-md bg-error-container px-4 py-2 text-body-sm text-on-error-container">
          <Icon name="error" size={17} />
          <span>{error}</span>
          <button type="button" className="ml-auto cursor-pointer" onClick={() => setError("")} aria-label={t("关闭错误提示")}>
            <Icon name="close" size={16} />
          </button>
        </div>
      )}

      {restoring ? (
        <div className="flex-1 min-h-0 flex flex-col items-center justify-center gap-3 text-on-surface-variant">
          <LoadingIndicator size={28} />
          <p className="text-body-sm">{t("正在恢复评估现场…")}</p>
        </div>
      ) : reportAssessment && reportRun ? (
        <RunWorkspace
          mode="reports"
          batch={reportBatch}
          activeRun={reportRun}
          activeRunId={reportAssessment.id}
          candidates={candidates}
          jds={jds}
          selectedNode={selectedNode}
          selectedNodeId={selectedNodeId}
          assessment={reportAssessment}
          reportAssessments={assessments}
          onSelectRun={openReport}
          onSelectNode={selectGraphNode}
          onCancelRun={() => {}}
        />
      ) : batch ? (
        <RunWorkspace
          batch={batch}
          activeRun={activeRun}
          activeRunId={activeRunId}
          candidates={candidates}
          jds={jds}
          selectedNode={selectedNode}
          selectedNodeId={selectedNodeId}
          assessment={activeAssessment}
          onSelectRun={(id) => {
            setActiveRunId(id);
            setSelectedNode(null);
            setSelectedNodeId(null);
          }}
          onSelectNode={selectGraphNode}
          onCancelRun={async (runId) => {
            await api.interviewAssessments.cancelRun(runId);
            await hydrateBatch(batch.id);
          }}
        />
      ) : (
        <SelectionWorkspace
          candidates={candidates}
          jds={jds}
          candidateIds={candidateIds}
          jdIds={jdIds}
          candidateSearch={candidateSearch}
          jdSearch={jdSearch}
          force={force}
          assessments={assessments}
          onCandidateSearch={setCandidateSearch}
          onJdSearch={setJdSearch}
          onCandidateIds={updateCandidateIds}
          onJdIds={updateJdIds}
          onOpenReport={openReport}
          onStart={start}
          starting={starting}
        />
      )}
    </div>
  );
}

function BatchSummary({ batch }: { batch: InterviewAssessmentBatch }) {
  const done = batch.completed_pairs + batch.failed_pairs + batch.cancelled_pairs;
  const progress = batch.total_pairs ? done / batch.total_pairs * 100 : 0;
  return (
    <div className="hidden lg:flex w-[360px] items-center gap-3">
      <Progress value={progress} className="flex-1" />
      <span className="text-label tabular-nums text-on-surface-variant">{done} / {batch.total_pairs}</span>
    </div>
  );
}

function ReportSummary({ assessments }: { assessments: InterviewAssessment[] }) {
  const { t } = useI18n();
  const valid = assessments.filter((item) => item.is_valid).length;
  return (
    <div className="hidden lg:flex items-center gap-3 text-label text-on-surface-variant">
      <span>{t("{n} 份已有报告", { n: assessments.length })}</span>
      <span className="w-6 border-t border-outline-variant" />
      <span>{t("{n} 份有效", { n: valid })}</span>
      {!!(assessments.length - valid) && (
        <>
          <span className="w-6 border-t border-outline-variant" />
          <span className="text-warning">{t("{n} 份需重评", { n: assessments.length - valid })}</span>
        </>
      )}
    </div>
  );
}

function SelectionWorkspace({
  candidates,
  jds,
  candidateIds,
  jdIds,
  candidateSearch,
  jdSearch,
  force,
  assessments,
  onCandidateSearch,
  onJdSearch,
  onCandidateIds,
  onJdIds,
  onOpenReport,
  onStart,
  starting,
}: {
  candidates: CandidateBrief[];
  jds: JdEntry[];
  candidateIds: Set<string>;
  jdIds: Set<string>;
  candidateSearch: string;
  jdSearch: string;
  force: boolean;
  assessments: InterviewAssessment[];
  onCandidateSearch: (value: string) => void;
  onJdSearch: (value: string) => void;
  onCandidateIds: (value: Set<string>) => void;
  onJdIds: (value: Set<string>) => void;
  onOpenReport: (id: string) => void;
  onStart: () => void;
  starting: boolean;
}) {
  const { t } = useI18n();
  const filteredCandidates = useMemo(() => {
    const query = candidateSearch.trim().toLowerCase();
    if (!query) return candidates;
    return candidates.filter((candidate) => [candidate.name, candidate.role, candidate.stage, candidate.group]
      .some((value) => value?.toLowerCase().includes(query)));
  }, [candidateSearch, candidates]);
  const filteredJds = useMemo(() => {
    const query = jdSearch.trim().toLowerCase();
    if (!query) return jds;
    return jds.filter((jd) => [jd.title, jd.team, jd.assessment_card?.role_summary]
      .some((value) => value?.toLowerCase().includes(query)));
  }, [jdSearch, jds]);

  const toggle = (current: Set<string>, id: string, onChange: (value: Set<string>) => void) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onChange(next);
  };

  const selectedCandidates = candidates.filter((candidate) => candidateIds.has(candidate.id));
  const selectedJds = jds.filter((jd) => jdIds.has(jd.id));
  const pairCount = candidateIds.size * jdIds.size;
  const selectedExistingAssessments = assessments.filter((item) => (
    item.is_valid && candidateIds.has(item.candidate_id) && jdIds.has(item.jd_id)
  ));

  return (
    <div className="app-workspace-frame grid w-full max-w-full grid-cols-1 xl:grid-cols-[minmax(270px,0.9fr)_minmax(430px,1.55fr)_minmax(300px,1fr)] gap-4 min-w-0 overflow-y-auto xl:overflow-hidden">
      <SelectionPanel
        title={t("候选人")}
        count={candidates.length}
        selectedCount={candidateIds.size}
        search={candidateSearch}
        searchPlaceholder={t("搜索姓名、方向或阶段")}
        onSearch={onCandidateSearch}
        onSelectVisible={() => onCandidateIds(new Set(filteredCandidates.map((candidate) => candidate.id)))}
        onClear={() => onCandidateIds(new Set())}
      >
        {filteredCandidates.map((candidate) => {
          const selected = candidateIds.has(candidate.id);
          return (
            <button
              type="button"
              key={candidate.id}
              onClick={() => toggle(candidateIds, candidate.id, onCandidateIds)}
              className={cn(
                "group flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left transition-colors cursor-pointer",
                selected ? "bg-secondary-container" : "hover:bg-surface-low",
              )}
            >
              <span className={cn(
                "flex h-9 w-9 shrink-0 items-center justify-center rounded-full border-2 text-title transition-colors",
                selected ? "border-primary bg-primary text-on-primary" : "border-outline-variant bg-primary-container text-on-primary-container",
              )}>
                {selected ? <Icon name="check" size={17} /> : (candidate.name || "?").slice(0, 1)}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-body font-medium">{candidate.name || t("未命名")}</span>
                <span className="mt-0.5 block truncate text-body-sm text-on-surface-variant">
                  {[candidate.role, candidate.stage].filter(Boolean).join(" · ") || t("尚未标注方向")}
                </span>
              </span>
            </button>
          );
        })}
        {!filteredCandidates.length && <PanelEmpty icon="person_search" text={t("没有匹配的候选人")} />}
      </SelectionPanel>

      <Card variant="filled" className="relative min-h-[480px] xl:min-h-0 overflow-hidden flex flex-col">
        <div className="flex items-center justify-between border-b border-outline-variant px-4 py-3">
          <div>
            <p className="text-title">{t("配对关系预览")}</p>
            <p className="mt-0.5 text-label text-on-surface-variant">{t("每位候选人将分别对照每张岗位评估卡")}</p>
          </div>
          <StatusChip tone={pairCount ? "primary" : "neutral"}>{t("{n} 个配对", { n: pairCount })}</StatusChip>
        </div>
        <PairingPreviewGraph candidates={selectedCandidates} jds={selectedJds} />
        <div className="border-t border-outline-variant px-4 py-3">
          {!!selectedExistingAssessments.length && !force && (
            <button
              type="button"
              onClick={() => onOpenReport(selectedExistingAssessments[0].id)}
              className="mb-3 flex w-full cursor-pointer items-center gap-3 rounded-md border border-outline-variant bg-surface-lowest px-3 py-2.5 text-left transition-colors hover:bg-surface-low"
            >
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-container text-on-primary-container">
                <Icon name="description" size={17} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-body-sm font-medium">{t("已有 {n} 份有效报告", { n: selectedExistingAssessments.length })}</span>
                <span className="mt-0.5 block text-label text-on-surface-variant">{t("直接打开查看，不再重复评估")}</span>
              </span>
              <Icon name="arrow_forward" size={17} className="text-on-surface-variant" />
            </button>
          )}
          <Button
            className="w-full"
            icon={selectedExistingAssessments.length && !force ? "description" : "play_arrow"}
            disabled={!pairCount || starting}
            onClick={selectedExistingAssessments.length && !force ? () => onOpenReport(selectedExistingAssessments[0].id) : onStart}
          >
            {starting
              ? t("正在创建评估批次…")
              : selectedExistingAssessments.length && !force
                ? t("查看 {n} 份已有报告", { n: selectedExistingAssessments.length })
                : pairCount
                  ? t("开始评估 {n} 个配对", { n: pairCount })
                  : t("先从两侧完成选择")}
          </Button>
        </div>
      </Card>

      <SelectionPanel
        title={t("岗位 JD")}
        count={jds.length}
        selectedCount={jdIds.size}
        search={jdSearch}
        searchPlaceholder={t("搜索岗位或团队")}
        onSearch={onJdSearch}
        onSelectVisible={() => onJdIds(new Set(filteredJds.map((jd) => jd.id)))}
        onClear={() => onJdIds(new Set())}
      >
        {filteredJds.map((jd) => {
          const selected = jdIds.has(jd.id);
          return (
            <button
              type="button"
              key={jd.id}
              onClick={() => toggle(jdIds, jd.id, onJdIds)}
              className={cn(
                "group mb-1 flex w-full items-start gap-3 rounded-md border px-2.5 py-2.5 text-left transition-[background-color,border-color,box-shadow] cursor-pointer last:mb-0",
                selected
                  ? "border-outline bg-secondary-container shadow-[0_1px_2px_rgba(15,17,21,0.06)]"
                  : "border-transparent bg-surface-lowest hover:border-outline-variant hover:bg-surface-low",
              )}
            >
              <span className={cn(
                "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
                selected ? "border-primary bg-primary text-on-primary" : "border-outline-variant bg-surface-lowest text-on-surface-variant",
              )}>
                <Icon name={selected ? "check" : "work"} size={16} />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-body font-medium">{jd.title}</span>
                <span className="mt-0.5 block line-clamp-2 text-body-sm text-on-surface-variant">
                  {jd.assessment_card?.role_summary || jd.team || t("岗位评估卡已就绪")}
                </span>
                <span className="mt-1.5 block text-label text-on-surface-variant">
                  {t("{n} 项核心任务", { n: jd.assessment_card?.core_tasks.length || 0 })}
                </span>
              </span>
            </button>
          );
        })}
        {!filteredJds.length && <PanelEmpty icon="work_off" text={t("没有匹配且已就绪的岗位")} />}
      </SelectionPanel>
    </div>
  );
}

function SelectionPanel({
  title,
  count,
  selectedCount,
  search,
  searchPlaceholder,
  onSearch,
  onSelectVisible,
  onClear,
  children,
}: {
  title: string;
  count: number;
  selectedCount: number;
  search: string;
  searchPlaceholder: string;
  onSearch: (value: string) => void;
  onSelectVisible: () => void;
  onClear: () => void;
  children: React.ReactNode;
}) {
  const { t } = useI18n();
  return (
    <Card variant="filled" className="min-h-[420px] xl:min-h-0 min-w-0 overflow-hidden flex flex-col">
      <div className="border-b border-outline-variant px-3 py-3">
        <div className="mb-2.5 flex items-center gap-2">
          <p className="text-title">{title}</p>
          <span className="text-label text-on-surface-variant">{count}</span>
          <span className="ml-auto text-label text-on-surface-variant">{t("已选 {n}", { n: selectedCount })}</span>
        </div>
        <SearchField value={search} onChange={(event) => onSearch(event.target.value)} placeholder={searchPlaceholder} className="w-full h-9" />
        <div className="mt-2 flex items-center gap-3 text-label">
          <button type="button" onClick={onSelectVisible} className="cursor-pointer text-on-surface hover:underline underline-offset-4">{t("选择当前结果")}</button>
          {!!selectedCount && <button type="button" onClick={onClear} className="cursor-pointer text-on-surface-variant hover:text-on-surface">{t("清空")}</button>}
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-1.5 admission-panel-scrollbar">{children}</div>
    </Card>
  );
}

function PanelEmpty({ icon, text }: { icon: string; text: string }) {
  return (
    <div className="flex h-full min-h-48 flex-col items-center justify-center gap-2 text-on-surface-variant">
      <Icon name={icon} size={28} />
      <p className="text-body-sm">{text}</p>
    </div>
  );
}

function PairingPreviewGraph({ candidates, jds }: { candidates: CandidateBrief[]; jds: JdEntry[] }) {
  const { t } = useI18n();
  const visibleCandidates = candidates.slice(0, 5);
  const visibleJds = jds.slice(0, 5);
  const candidateY = (index: number) => 74 + index * 74;
  const jdY = (index: number) => 74 + index * 74;
  const height = Math.max(370, Math.max(visibleCandidates.length, visibleJds.length) * 74 + 80);
  return (
    <div className="relative flex-1 min-h-0 overflow-auto admission-panel-scrollbar">
      {!candidates.length && !jds.length ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-center text-on-surface-variant">
          <span className="admission-preview-empty-node flex h-14 w-14 items-center justify-center rounded-full bg-surface-lowest">
            <Icon name="account_tree" size={23} />
          </span>
          <p className="mt-4 text-body font-medium text-on-surface">{t("从两侧选择评估对象")}</p>
          <p className="mt-1 max-w-64 text-body-sm">{t("候选人与岗位会在这里建立显式配对，不再受全局激活状态影响")}</p>
        </div>
      ) : (
        <div className="relative min-w-[420px]" style={{ height }}>
          <svg className="absolute inset-0 h-full w-full" viewBox={`0 0 700 ${height}`} preserveAspectRatio="none" aria-hidden="true">
            {visibleCandidates.flatMap((_, ci) => visibleJds.map((__, ji) => (
              <path
                key={`${ci}-${ji}`}
                d={`M 174 ${candidateY(ci)} C 300 ${candidateY(ci)}, 400 ${jdY(ji)}, 526 ${jdY(ji)}`}
                className="admission-preview-edge"
              />
            )))}
          </svg>
          {visibleCandidates.map((candidate, index) => (
            <div key={candidate.id} className="absolute left-[12%] w-36 -translate-x-1/2 text-center" style={{ top: candidateY(index) - 21 }}>
              <span className="mx-auto flex h-10 w-10 items-center justify-center rounded-full border-2 border-outline bg-primary-container text-title text-on-primary-container">
                {(candidate.name || "?").slice(0, 1)}
              </span>
              <span className="mt-1 block truncate text-label text-on-surface-variant">{candidate.name || t("未命名")}</span>
            </div>
          ))}
          {visibleJds.map((jd, index) => (
            <div key={jd.id} className="absolute left-[88%] w-40 -translate-x-1/2 text-center" style={{ top: jdY(index) - 21 }}>
              <span className="mx-auto flex h-10 w-10 items-center justify-center rounded-full border border-outline bg-surface-lowest text-on-surface-variant">
                <Icon name="work" size={17} />
              </span>
              <span className="mt-1 block truncate text-label text-on-surface-variant">{jd.title}</span>
            </div>
          ))}
          {candidates.length > visibleCandidates.length && <span className="absolute bottom-4 left-[12%] -translate-x-1/2 text-label text-on-surface-variant">{t("另有 {n} 人", { n: candidates.length - visibleCandidates.length })}</span>}
          {jds.length > visibleJds.length && <span className="absolute bottom-4 left-[88%] -translate-x-1/2 text-label text-on-surface-variant">{t("另有 {n} 个岗位", { n: jds.length - visibleJds.length })}</span>}
        </div>
      )}
    </div>
  );
}

function RunWorkspace({
  mode = "run",
  batch,
  activeRun,
  activeRunId,
  candidates,
  jds,
  selectedNode,
  selectedNodeId,
  assessment,
  reportAssessments = [],
  onSelectRun,
  onSelectNode,
  onCancelRun,
}: {
  mode?: "run" | "reports";
  batch: InterviewAssessmentBatch;
  activeRun?: InterviewAssessmentRun;
  activeRunId: string | null;
  candidates: CandidateBrief[];
  jds: JdEntry[];
  selectedNode: AdmissionGraphNode | null;
  selectedNodeId: string | null;
  assessment?: InterviewAssessment;
  reportAssessments?: InterviewAssessment[];
  onSelectRun: (id: string) => void;
  onSelectNode: (node: AdmissionGraphNode) => void;
  onCancelRun: (id: string) => void;
}) {
  const { t } = useI18n();
  const candidate = candidates.find((item) => item.id === activeRun?.candidate_id);
  const jd = jds.find((item) => item.id === activeRun?.jd_id);
  return (
    <div className="app-workspace-frame grid w-full max-w-full grid-cols-1 xl:grid-cols-[minmax(250px,0.78fr)_minmax(560px,1.75fr)_minmax(300px,0.95fr)] gap-4 min-w-0 overflow-y-auto xl:overflow-hidden">
      <Card variant="filled" className="min-h-[300px] xl:min-h-0 overflow-hidden flex flex-col">
        <div className="border-b border-outline-variant px-3 py-3">
          <div className="flex items-center justify-between">
            <p className="text-title">{mode === "reports" ? t("已有报告") : t("配对队列")}</p>
            <StatusChip tone={TERMINAL_BATCH_STATUSES.has(batch.status) ? "success" : "primary"}>
              {mode === "reports" ? batch.total_pairs : `${batch.completed_pairs}/${batch.total_pairs}`}
            </StatusChip>
          </div>
          <p className="mt-1 text-label text-on-surface-variant">
            {mode === "reports" ? t("点击候选人 × 岗位查看完整报告") : t("全局最多并行评估 5 个配对")}
          </p>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto p-1.5 admission-panel-scrollbar">
          {(batch.runs || []).map((run) => (
            <RunRow
              key={run.id}
              run={run}
              candidate={candidates.find((item) => item.id === run.candidate_id)}
              jd={jds.find((item) => item.id === run.jd_id)}
              assessment={reportAssessments.find((item) => item.id === run.id)}
              active={run.id === activeRunId || (!activeRunId && run.id === activeRun?.id)}
              onClick={() => onSelectRun(run.id)}
            />
          ))}
        </div>
      </Card>

      <Card variant="filled" className="relative min-h-[600px] xl:min-h-0 overflow-hidden flex flex-col">
        <div className="flex items-center gap-3 border-b border-outline-variant px-4 py-3 shrink-0">
          <div className="min-w-0">
            <p className="truncate text-title">{candidate?.name || t("候选人")} × {jd?.title || t("岗位")}</p>
            <p className="mt-0.5 truncate text-label text-on-surface-variant">
              {mode === "reports" ? t("报告生成时的真实调用链") : t("节点按真实调用顺序从上到下生长")}
            </p>
          </div>
          <div className="ml-auto flex items-center gap-3 text-[11px] text-on-surface-variant">
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-primary" />{t("运行")}</span>
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full border border-outline" />{t("完成")}</span>
            <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-error" />{t("异常")}</span>
          </div>
          {activeRun && !TERMINAL_RUN_STATUSES.has(activeRun.status) && (
            <IconButton icon="stop_circle" onClick={() => onCancelRun(activeRun.id)} title={t("停止此配对")} />
          )}
        </div>
        <div className="flex-1 min-h-0 overflow-auto admission-panel-scrollbar">
          {activeRun ? (
            <AdmissionWorkflowGraph
              run={activeRun}
              candidate={candidate}
              jd={jd}
              selectedNodeId={selectedNodeId}
              onSelectNode={onSelectNode}
            />
          ) : (
            <PanelEmpty icon="account_tree" text={t("等待运行信息")} />
          )}
        </div>
      </Card>

      <Card variant="filled" className="min-h-[420px] xl:min-h-0 overflow-hidden flex flex-col">
        <div className="border-b border-outline-variant px-4 py-3 shrink-0">
          <p className="text-title">{assessment ? t("评估结论与证据") : t("节点详情")}</p>
          <p className="mt-0.5 text-label text-on-surface-variant">{t("点击图中节点查看当前产物")}</p>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto p-4 admission-panel-scrollbar">
          {assessment && <AssessmentPanel assessment={assessment} run={activeRun} jd={jd} />}
          {assessment && selectedNode && <div className="my-4 border-t border-outline-variant" />}
          <NodeInspector node={selectedNode} />
          {activeRun?.error_message && (
            <div className="mt-4 rounded-md bg-error-container p-3 text-body-sm text-on-error-container">
              <p className="font-medium">{t("运行失败")}</p>
              <p className="mt-1">{activeRun.error_message}</p>
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}

function RunRow({ run, candidate, jd, assessment, active, onClick }: {
  run: InterviewAssessmentRun;
  candidate?: CandidateBrief;
  jd?: JdEntry;
  assessment?: InterviewAssessment;
  active: boolean;
  onClick: () => void;
}) {
  const { t } = useI18n();
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full rounded-md px-2.5 py-2.5 text-left transition-colors cursor-pointer",
        active ? "bg-secondary-container" : "hover:bg-surface-low",
      )}
    >
      <span className="flex items-center gap-2">
        <span className="truncate text-body font-medium">{candidate?.name || run.candidate_id}</span>
        <StatusChip
          tone={assessment ? (assessment.is_valid ? (assessment.decision === "interview" ? "success" : "error") : "warning") : (RUN_STATUS_TONE[run.status] || "neutral")}
          className="ml-auto shrink-0"
        >
          {assessment
            ? assessment.is_valid
              ? assessment.decision === "interview" ? t("进入面试") : t("不进入面试")
              : t("需重评")
            : t(RUN_STATUS_LABEL[run.status] || run.status)}
        </StatusChip>
      </span>
      <span className="mt-1 block truncate text-label text-on-surface-variant">{jd?.title || run.jd_id}</span>
      {run.current_node && run.status === "running" && (
        <span className="mt-2 block h-0.5 overflow-hidden rounded-full bg-surface-highest">
          <span className="admission-run-row-flow block h-full w-1/3 bg-primary" />
        </span>
      )}
    </button>
  );
}

function AssessmentPanel({ assessment, run, jd }: {
  assessment: InterviewAssessment;
  run?: InterviewAssessmentRun;
  jd?: JdEntry;
}) {
  const { t } = useI18n();
  const tasks = assessment.task_assessments as TaskAssessmentView[];
  const decisionReason = [...(run?.run_trace || [])].reverse().find((event) => event.node_id === "admission_decision")?.summary;
  return (
    <section>
      <div className="flex items-center gap-2">
        <StatusChip tone={assessment.decision === "interview" ? "success" : "error"} variant="filled">
          {assessment.decision === "interview" ? t("进入面试") : t("不进入面试")}
        </StatusChip>
        {!assessment.is_valid && <StatusChip tone="warning">{t("需重评")}</StatusChip>}
      </div>
      <div className="mt-3 flex items-baseline gap-1">
        <span className="text-headline tabular-nums">{assessment.total_score.toFixed(1)}</span>
        <span className="text-body-sm text-on-surface-variant">{t("/100 核心任务")}</span>
      </div>
      {decisionReason && <p className="mt-2 text-body-sm text-on-surface-variant">{decisionReason}</p>}
      <div className="mt-4 flex flex-col gap-2">
        {tasks.map((task) => {
          const cardTask = jd?.assessment_card?.core_tasks.find((item) => item.id === task.task_id);
          return (
            <details key={task.task_id} className="border-t border-outline-variant pt-2" open={(task.level || 0) < 2}>
              <summary className="flex cursor-pointer list-none items-center gap-2">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-outline-variant font-mono text-label tabular-nums">{task.level ?? 0}</span>
                <span className="min-w-0 flex-1 truncate text-body-sm font-medium">{cardTask?.title || task.task_id}</span>
                <span className="text-label text-on-surface-variant">{confidenceLabel(task.confidence, t)}</span>
              </summary>
              <p className="mt-2 text-body-sm text-on-surface-variant">{task.reasoning_summary || t("暂无推理摘要")}</p>
              {!!task.evidence?.length && (
                <div className="mt-2 flex flex-col gap-1.5">
                  {task.evidence.map((evidence, index) => <EvidenceQuote key={`${evidence.quote}-${index}`} evidence={evidence} />)}
                </div>
              )}
              {!!task.risks?.length && (
                <ul className="mt-2 list-disc space-y-1 pl-4 text-label text-on-surface-variant">
                  {task.risks.map((risk) => <li key={risk}>{risk}</li>)}
                </ul>
              )}
            </details>
          );
        })}
      </div>
      {!!assessment.review_corrections.length && (
        <div className="mt-4 border-t border-outline-variant pt-3">
          <p className="text-label font-semibold">{t("总审纠错记录")}</p>
          <div className="mt-2 flex flex-col gap-2">
            {assessment.review_corrections.map((correction, index) => {
              const item = correction as Record<string, unknown>;
              return (
                <div key={index} className="text-label text-on-surface-variant">
                  <span className="font-medium text-on-surface">{String(item.task_id || t("任务"))}</span>
                  <span className="mx-1 tabular-nums">{String(item.original_level ?? "—")} → {String(item.revised_level ?? "—")}</span>
                  <span>{String(item.reason || "")}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </section>
  );
}

function EvidenceQuote({ evidence }: { evidence: EvidenceView }) {
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

function NodeInspector({ node }: { node: AdmissionGraphNode | null }) {
  const { t } = useI18n();
  if (!node) return <PanelEmpty icon="touch_app" text={t("选择一个节点查看详情")} />;
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

function confidenceLabel(value: string | undefined, t: Translate) {
  return value === "high" ? t("高置信") : value === "medium" ? t("中置信") : value === "low" ? t("低置信") : "—";
}
