import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import type {
  CandidateBrief,
  CandidateDetail,
  InterviewAssessment,
  InterviewAssessmentBatch,
  InterviewAssessmentRun,
  JdEntry,
} from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import Button from "@/components/ui/Button";
import Icon from "@/components/ui/Icon";
import Card from "@/components/ui/Card";
import Progress from "@/components/ui/Progress";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import type { AdmissionGraphNode } from "@/features/admission/AdmissionWorkflowGraph";
import CandidateFolderTree from "@/features/talentEvaluation/CandidateFolderTree";
import AdmissionPane from "@/features/talentEvaluation/AdmissionPane";
import { BatchQueueCard } from "@/features/talentEvaluation/BatchViews";
import ImportOverlay from "@/features/resume/ImportOverlay";
import { buildCandidateFolders } from "@/features/talentEvaluation/talentEvaluationModel";
import { useSessionState } from "@/lib/sessionState";
import { useI18n } from "@/lib/i18n";

const TERMINAL_BATCH_STATUSES = new Set(["completed", "failed", "cancelled"]);
/** 导入进行中标记：SSE 断连（刷新）后用于提示"后台可能仍在导入" */
const IMPORT_FLAG = "talent-evaluation.import-in-flight";

/**
 * 统一"人才评估"外壳（docs/rebuild.md §2）。
 * 当前只承载面试准入子界面；能力评估入口暂时移除（维度确认前不提供占位），
 * /talent-evaluation/capability 由路由重定向回 admission。
 */
export default function TalentEvaluation() {
  const { t } = useI18n();

  // ---- 数据 ----
  const [candidates, setCandidates] = useState<CandidateBrief[]>([]);
  const [allJds, setAllJds] = useState<JdEntry[]>([]);
  const [assessments, setAssessments] = useState<InterviewAssessment[]>([]);
  const [activeRuns, setActiveRuns] = useState<InterviewAssessmentRun[]>([]);
  const [batch, setBatch] = useState<InterviewAssessmentBatch | null>(null);
  const [candidateDetail, setCandidateDetail] = useState<CandidateDetail | null>(null);
  const [candidateDetailLoading, setCandidateDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  // ---- 会话恢复的现场（刷新 / 短暂离开不丢） ----
  const [selectedCandidateId, setSelectedCandidateId] = useSessionState<string | null>("talent-evaluation.candidate-id", null);
  const [selectedJdId, setSelectedJdId] = useSessionState<string | null>("talent-evaluation.jd-id", null);
  const [batchId, setBatchId] = useSessionState<string | null>("talent-evaluation.batch-id", null);
  const [activeRunId, setActiveRunId] = useSessionState<string | null>("talent-evaluation.active-run-id", null);
  const [selectedNodeId, setSelectedNodeId] = useSessionState<string | null>("talent-evaluation.node-id", null);
  const [treeSearch, setTreeSearch] = useSessionState("talent-evaluation.tree-search", "");
  const [openFolderIds, setOpenFolderIds] = useSessionState<string[]>("talent-evaluation.open-folders", []);
  const [draftCandidateIds, setDraftCandidateIds] = useSessionState<string[]>("talent-evaluation.draft-candidate-ids", []);
  const [draftJdIds, setDraftJdIds] = useSessionState<string[]>("talent-evaluation.draft-jd-ids", []);
  const [draftCandidateSearch, setDraftCandidateSearch] = useSessionState("talent-evaluation.draft-candidate-search", "");
  const [draftJdSearch, setDraftJdSearch] = useSessionState("talent-evaluation.draft-jd-search", "");

  // ---- 临时态 ----
  const [creating, setCreating] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importRecovering, setImportRecovering] = useState(() => {
    try {
      return sessionStorage.getItem(IMPORT_FLAG) === "1";
    } catch {
      return false;
    }
  });
  const [selectedNode, setSelectedNode] = useState<AdmissionGraphNode | null>(null);
  const [restoring, setRestoring] = useState(false);
  const batchIdRef = useRef<string | null>(null);
  const detailIdRef = useRef<string | null>(null);

  const folders = useMemo(
    () => buildCandidateFolders(candidates, assessments, activeRuns),
    [candidates, assessments, activeRuns],
  );

  // ---- 数据加载 ----
  const loadShell = useCallback(async () => {
    try {
      // 候选人目录与人才库同源：已入库或拥有准入报告的人（导入即入库）
      const [candidateRows, jdRows, assessmentRows, activeRows] = await Promise.all([
        api.candidates.list(),
        api.jds.list(),
        api.interviewAssessments.list(),
        api.interviewAssessments.active(),
      ]);
      setCandidates(candidateRows);
      setAllJds(jdRows);
      setAssessments(assessmentRows);
      setActiveRuns(activeRows);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("加载失败"));
    }
  }, [t]);

  const refreshActiveRuns = useCallback(async () => {
    try {
      setActiveRuns(await api.interviewAssessments.active());
    } catch {
      /* 轮询失败静默，下轮重试 */
    }
  }, []);

  useEffect(() => {
    void loadShell();
  }, [loadShell]);

  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible") void loadShell();
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [loadShell]);

  const hydrateBatch = useCallback(async (id: string) => {
    // 批次已被重置（返回浏览）时丢弃这次恢复请求
    if (batchIdRef.current !== id) return;
    try {
      const next = await api.interviewAssessments.batch(id);
      setBatch(next);
      setActiveRunId((current) => (
        current && next.runs?.some((run) => run.id === current) ? current : next.runs?.[0]?.id || null
      ));
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

  // 批次恢复与轮询：持久化以服务端运行记录为准
  useEffect(() => {
    batchIdRef.current = batchId;
    if (!batchId) {
      setRestoring(false);
      return;
    }
    setRestoring(true);
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

  // 活动配对轮询：所有用户通过活动运行接口实时看到占用状态
  const batchRunning = !!batch && !TERMINAL_BATCH_STATUSES.has(batch.status);
  useEffect(() => {
    if (!activeRuns.length && !batchRunning) return;
    const refresh = () => {
      if (document.visibilityState === "visible") void refreshActiveRuns();
    };
    const timer = window.setInterval(refresh, 1200);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [activeRuns.length, batchRunning, refreshActiveRuns]);

  // 选中候选人的档案详情
  useEffect(() => {
    if (!selectedCandidateId) {
      detailIdRef.current = null;
      setCandidateDetail(null);
      return;
    }
    const id = selectedCandidateId;
    detailIdRef.current = id;
    setCandidateDetailLoading(true);
    api.candidates.get(id)
      .then((detail) => {
        if (detailIdRef.current === id) setCandidateDetail(detail);
      })
      .catch(() => {
        if (detailIdRef.current === id) setCandidateDetail(null);
      })
      .finally(() => {
        if (detailIdRef.current === id) setCandidateDetailLoading(false);
      });
  }, [selectedCandidateId]);

  // 简历卡片内的人工裁决后静默刷新详情（不整页 loading）
  const refreshDetail = useCallback(() => {
    const id = detailIdRef.current;
    if (!id) return;
    api.candidates.get(id)
      .then((detail) => {
        if (detailIdRef.current === detail.id) setCandidateDetail(detail);
      })
      .catch(() => {
        /* 静默失败 */
      });
  }, []);

  // 选择失效时清理（候选人被物理删除等）
  useEffect(() => {
    if (!selectedCandidateId) return;
    const stillVisible = candidates.some((item) => item.id === selectedCandidateId)
      || assessments.some((item) => item.candidate_id === selectedCandidateId);
    if (!stillVisible) {
      setSelectedCandidateId(null);
      setSelectedJdId(null);
    }
  }, [candidates, assessments, selectedCandidateId, setSelectedCandidateId, setSelectedJdId]);

  // 选中的候选人文件夹自动展开
  useEffect(() => {
    if (!selectedCandidateId) return;
    setOpenFolderIds((current) => (
      current.includes(selectedCandidateId) ? current : [...current, selectedCandidateId]
    ));
  }, [selectedCandidateId, setOpenFolderIds]);

  // 人才库批量评估跳转兼容：?focus=<candidate_id>
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    const focus = searchParams.get("focus");
    if (!focus) return;
    setSearchParams({}, { replace: true });
    setSelectedCandidateId(focus);
    setSelectedJdId(null);
    void loadShell();
  }, [searchParams, setSearchParams, setSelectedCandidateId, setSelectedJdId, loadShell]);

  // ---- 批次操作 ----
  const startBatch = useCallback(async (candidateIds: string[], jdIds: string[]) => {
    if (!candidateIds.length || !jdIds.length || starting) return;
    setStarting(true);
    setError("");
    try {
      const next = await api.interviewAssessments.start(candidateIds, jdIds);
      setBatch(next);
      setBatchId(next.id);
      setActiveRunId(next.runs?.[0]?.id || null);
      setSelectedNodeId(null);
      setSelectedNode(null);
      setCreating(false);
      void refreshActiveRuns();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("启动失败"));
      void loadShell();
    } finally {
      setStarting(false);
    }
  }, [loadShell, refreshActiveRuns, setActiveRunId, setBatchId, setSelectedNodeId, starting, t]);

  const cancelRun = useCallback(async (runId: string) => {
    try {
      await api.interviewAssessments.cancelRun(runId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("停止失败"));
    }
    if (batchId) await hydrateBatch(batchId);
    await loadShell();
  }, [batchId, hydrateBatch, loadShell, t]);

  const cancelBatch = useCallback(async () => {
    if (!batchId) return;
    try {
      await api.interviewAssessments.cancelBatch(batchId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("停止失败"));
    }
    await hydrateBatch(batchId);
    await loadShell();
  }, [batchId, hydrateBatch, loadShell, t]);

  const resetBatch = useCallback(() => {
    setBatchId(null);
    setBatch(null);
    setActiveRunId(null);
    setSelectedNodeId(null);
    setSelectedNode(null);
    setError("");
    setRestoring(false);
  }, [setActiveRunId, setBatchId, setSelectedNodeId]);

  // ---- 左侧文件夹选择 ----
  const clearNode = useCallback(() => {
    setSelectedNodeId(null);
    setSelectedNode(null);
  }, [setSelectedNodeId]);

  const selectCandidateRoot = useCallback((candidateId: string) => {
    setSelectedCandidateId(candidateId);
    setSelectedJdId(null);
    clearNode();
  }, [clearNode, setSelectedCandidateId, setSelectedJdId]);

  const selectPair = useCallback((candidateId: string, jdId: string) => {
    setSelectedCandidateId(candidateId);
    setSelectedJdId(jdId);
    clearNode();
  }, [clearNode, setSelectedCandidateId, setSelectedJdId]);

  const selectGraphNode = useCallback((node: AdmissionGraphNode) => {
    setSelectedNode(node);
    setSelectedNodeId(node.id);
  }, [setSelectedNodeId]);

  const selectRun = useCallback((runId: string) => {
    // 进入批次运行视图：清掉左树的显式选择，让 AdmissionPane 显示 BatchRunView
    setSelectedCandidateId(null);
    setSelectedJdId(null);
    setActiveRunId(runId);
    clearNode();
  }, [clearNode, setActiveRunId, setSelectedCandidateId, setSelectedJdId]);

  // ---- 导入简历（共用动作，位于左侧候选人卡片底部） ----
  const openImport = useCallback(() => {
    setImportOpen(true);
    try {
      sessionStorage.setItem(IMPORT_FLAG, "1");
    } catch {
      /* ignore */
    }
  }, []);

  const closeImport = useCallback(() => {
    setImportOpen(false);
    setImportRecovering(false);
    try {
      sessionStorage.removeItem(IMPORT_FLAG);
    } catch {
      /* ignore */
    }
    void loadShell();
  }, [loadShell]);

  const runningCard = importOpen ? (
    <ImportOverlay onCandidate={() => void loadShell()} onClose={closeImport} />
  ) : importRecovering ? (
    <div className="shrink-0 border-t border-outline-variant p-3">
      <div className="rounded-md border border-outline-variant bg-surface-low px-3 py-2.5 text-label text-on-surface-variant">
        <p className="flex items-center gap-1.5">
          <Icon name="history" size={14} />
          {t("上次导入可能仍在后台进行")}
        </p>
        <p className="mt-1">{t("完成的简历会自动出现在候选人列表中")}</p>
        <div className="mt-2 flex items-center gap-3">
          <button type="button" className="cursor-pointer text-on-surface hover:underline underline-offset-4" onClick={() => void loadShell()}>
            {t("刷新列表")}
          </button>
          <button
            type="button"
            className="cursor-pointer hover:underline underline-offset-4"
            onClick={() => {
              setImportRecovering(false);
              try {
                sessionStorage.removeItem(IMPORT_FLAG);
              } catch {
                /* ignore */
              }
            }}
          >
            {t("知道了")}
          </button>
        </div>
      </div>
    </div>
  ) : null;

  const selectedChildKey = selectedJdId ? `jd:${selectedJdId}` : null;

  const batchDone = batch && TERMINAL_BATCH_STATUSES.has(batch.status)
    ? batch.completed_pairs + batch.failed_pairs + batch.cancelled_pairs
    : 0;

  return (
    <div className="w-full max-w-full min-w-0">
      <PageToolbar
        title={t("人才评估")}
        subtitle={t("面试准入：判断候选人是否值得进入某个岗位的面试")}
        right={
          <>
            {batchRunning ? (
              <div className="hidden lg:flex w-[240px] items-center gap-3">
                <Progress value={batch!.total_pairs ? (batchDone / batch!.total_pairs) * 100 : 0} className="flex-1" />
                <span className="text-label tabular-nums text-on-surface-variant">{batchDone} / {batch!.total_pairs}</span>
              </div>
            ) : batch ? (
              <Button variant="tonal" icon="add" onClick={resetBatch}>{t("返回浏览")}</Button>
            ) : !creating ? (
              <Button variant="filled" icon="add" onClick={() => setCreating(true)}>{t("新建准入评估")}</Button>
            ) : null}
          </>
        }
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

      <div className="app-workspace-frame grid w-full max-w-full grid-cols-1 gap-4 min-w-0 min-h-0 overflow-y-auto xl:grid-cols-[300px_minmax(0,1fr)] xl:overflow-hidden">
        <CandidateFolderTree
          folders={folders}
          search={treeSearch}
          onSearch={setTreeSearch}
          openFolderIds={openFolderIds}
          onToggleFolder={(candidateId) => setOpenFolderIds((current) => (
            current.includes(candidateId)
              ? current.filter((id) => id !== candidateId)
              : [...current, candidateId]
          ))}
          selectedCandidateId={selectedCandidateId}
          selectedChildKey={selectedChildKey}
          onSelectCandidate={selectCandidateRoot}
          onSelectPair={selectPair}
          runningCard={runningCard}
          queueCard={batch && !TERMINAL_BATCH_STATUSES.has(batch.status) ? (
            <BatchQueueCard
              batch={batch}
              activeRunId={activeRunId}
              onSelectRun={selectRun}
              onCancelBatch={() => void cancelBatch()}
            />
          ) : undefined}
          onImport={openImport}
        />

        <div className="min-w-0 min-h-0 flex flex-col">
          {restoring && !batch ? (
            <Card variant="filled" className="min-h-0 flex-1 items-center justify-center">
              <div className="flex flex-1 flex-col items-center justify-center gap-3 text-on-surface-variant">
                <LoadingIndicator size={28} />
                <p className="text-body-sm">{t("正在恢复评估现场…")}</p>
              </div>
            </Card>
          ) : (
            <AdmissionPane
              creating={creating}
              batch={batch}
              candidates={candidates}
              allJds={allJds}
              assessments={assessments}
              activeRuns={activeRuns}
              selectedCandidateId={selectedCandidateId}
              selectedJdId={selectedJdId}
              candidateDetail={candidateDetail}
              candidateDetailLoading={candidateDetailLoading}
              selectedNode={selectedNode}
              selectedNodeId={selectedNodeId}
              activeRunId={activeRunId}
              draftCandidateIds={new Set(draftCandidateIds)}
              draftJdIds={new Set(draftJdIds)}
              draftCandidateSearch={draftCandidateSearch}
              draftJdSearch={draftJdSearch}
              starting={starting}
              onCandidateReviewed={() => {
                refreshDetail();
                void loadShell();
              }}
              onDraftCandidateIds={(value) => setDraftCandidateIds([...value])}
              onDraftJdIds={(value) => setDraftJdIds([...value])}
              onDraftCandidateSearch={setDraftCandidateSearch}
              onDraftJdSearch={setDraftJdSearch}
              onSelectNode={selectGraphNode}
              onCancelRun={(runId) => void cancelRun(runId)}
              onExitCreate={() => setCreating(false)}
              onStartBatch={startBatch}
            />
          )}
        </div>
      </div>
    </div>
  );
}
