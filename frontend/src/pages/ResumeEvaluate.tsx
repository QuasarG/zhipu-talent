import { useState, useEffect, useCallback, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import { parseSSE } from "@/lib/api";
import type { CandidateBrief, CandidateDetail, EvaluationNodeRun } from "@/lib/types";
import { useSessionState } from "@/lib/sessionState";
import PageToolbar from "@/components/layout/PageToolbar";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import Button from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/Chip";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import CandidateQueue from "@/features/resume/CandidateQueue";
import ResumeContent from "@/features/resume/ResumeContent";
import EvaluationWorkspace from "@/features/resume/EvaluationWorkspace";
import ImportOverlay from "@/features/resume/ImportOverlay";
import CandidateMetaDropdown from "@/features/resume/CandidateMetaDropdown";
import { useI18n } from "@/lib/i18n";

/** 把单次 LLM 响应流里的完整字段组增量合并进详情 */
function mergePreviewFields(
  base: CandidateDetail,
  fields: Record<string, unknown>,
): CandidateDetail {
  const listKeys = ["education", "directions", "experiences", "projects", "publications", "skills", "screening_tags"] as const;
  const next = { ...base };
  for (const key of listKeys) {
    const incoming = fields[key];
    if (Array.isArray(incoming) && incoming.length > 0) {
      const existing = (next[key] as unknown[]) || [];
      const seen = new Set(existing.map((item) => JSON.stringify(item)));
      const merged = [...existing];
      for (const item of incoming) {
        const k = JSON.stringify(item);
        if (!seen.has(k)) { seen.add(k); merged.push(item); }
      }
      next[key] = merged as never;
    }
  }
  for (const key of ["name", "stage", "role"] as const) {
    const incoming = key === "role" ? (fields.target_role ?? fields.role) : fields[key];
    if (typeof incoming === "string" && incoming.trim() && !(next[key] as string)) {
      next[key] = incoming as never;
    }
  }
  return next;
}

/** 导入预览的最小合法详情（字段随分节解析逐步填充） */
function createImportPreview(fileName: string): CandidateDetail {
  return {
    id: `importing-${fileName}`,
    name: "", role: "", stage: "", group: "importing",
    level: "", category: "", engagement_status: "", admitted_at: null,
    confidence: 0, raw_text: "",
    education: [], directions: [], experiences: [], projects: [],
    publications: [], skills: [], screening_tags: [],
    source_format: "", document_analysis: {}, person_id: null, sources: [],
    evaluation_graph: { phases: [] },
  } as CandidateDetail;
}

export default function ResumeEvaluate() {
  const [candidates, setCandidates] = useState<CandidateBrief[]>([]);
  const [selected, setSelected] = useState<CandidateDetail | null>(null);
  const [selectedId, setSelectedId] = useSessionState<string | null>("resume-evaluate.selected-id", null);
  const [loading, setLoading] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [liveNodeRuns, setLiveNodeRuns] = useState<EvaluationNodeRun[]>([]);
  const [showImport, setShowImport] = useState(false);
  const [importPreview, setImportPreview] = useState<CandidateDetail | null>(null);
  const { t } = useI18n();
  // 跟踪当前选中候选人：SSE 闭包用它判断"用户是否已切走"，避免残留状态污染
  const currentIdRef = useRef<string | null>(null);
  // 当前正在跑评估的候选人 abort 控制器
  const evalAbortRef = useRef<AbortController | null>(null);

  const loadCandidates = useCallback(async () => {
    try {
      const list = await api.candidates.list();
      setCandidates(list);
    } catch (err) {
      console.error("加载候选人失败", err);
    }
  }, []);

  /** 静默刷新当前详情（不触发 loading，保持滚动位置）——人工裁决后用 */
  const refreshSelectedSilently = useCallback(async () => {
    if (!selectedId) return;
    try {
      const detail = await api.candidates.get(selectedId);
      setSelected(detail);
      setLiveNodeRuns(detail.evaluation_run?.node_runs || []);
      setEvaluating(detail.evaluation_run?.status === "running");
      await loadCandidates();
    } catch (err) {
      console.error("刷新详情失败", err);
    }
  }, [selectedId, loadCandidates]);

  useEffect(() => {
    loadCandidates();
  }, [loadCandidates]);

  useEffect(() => {
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") loadCandidates();
    };
    window.addEventListener("focus", loadCandidates);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.removeEventListener("focus", loadCandidates);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [loadCandidates]);

  // 有候选人正在核验中时，每 5 秒刷新列表拿最新状态
  useEffect(() => {
    const needsStatusRefresh = candidates.some((candidate) =>
      candidate.academic_check_status === "running"
      || candidate.verification_result === "needs_review"
      || candidate.evaluation_status === "running"
    );
    if (!needsStatusRefresh) return;
    const timer = setInterval(loadCandidates, 5000);
    return () => clearInterval(timer);
  }, [candidates, loadCandidates]);

  const selectCandidate = useCallback(async (id: string) => {
    // 切走时 abort 旧评估 SSE 流，防止残留闭包回写
    if (currentIdRef.current && currentIdRef.current !== id) {
      evalAbortRef.current?.abort();
      evalAbortRef.current = null;
    }
    currentIdRef.current = id;
    setSelectedId(id);
    setLoading(true);
    try {
      const detail = await api.candidates.get(id);
      // 异步回来后再确认用户没又切走
      if (currentIdRef.current !== id) return;
      setSelected(detail);
      setLiveNodeRuns(detail.evaluation_run?.node_runs || []);
      setEvaluating(detail.evaluation_run?.status === "running");
    } catch (err) {
      console.error("加载详情失败", err);
    } finally {
      if (currentIdRef.current === id) setLoading(false);
    }
  }, [setSelectedId]);

  useEffect(() => {
    if (!selectedId || selected || !candidates.some((candidate) => candidate.id === selectedId)) return;
    selectCandidate(selectedId);
  }, [candidates, selected, selectedId, selectCandidate]);

  // 人才库批量评估跳转：?focus=<candidate_id> → 刷新队列并选中该候选人
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    const focus = searchParams.get("focus");
    if (!focus) return;
    setSearchParams({}, { replace: true });
    loadCandidates().then(() => selectCandidate(focus));
  }, [searchParams, setSearchParams, selectCandidate, loadCandidates]);

  useEffect(() => {
    if (!selectedId || !selected?.evaluation_run || selected.evaluation_run.status !== "running") return;
    const timer = setInterval(async () => {
      try {
        const detail = await api.candidates.get(selectedId);
        setSelected(detail);
        setLiveNodeRuns(detail.evaluation_run?.node_runs || []);
        setEvaluating(detail.evaluation_run?.status === "running");
        if (detail.evaluation_run?.status !== "running") await loadCandidates();
      } catch (err) {
        console.error("恢复评估状态失败", err);
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [selectedId, selected?.evaluation_run, loadCandidates]);

  // 列表轮询拿到核验终态后，同步当前详情，避免评估按钮继续使用旧状态。
  useEffect(() => {
    if (!selectedId || !selected) return;
    const brief = candidates.find((candidate) => candidate.id === selectedId);
    if (!brief) {
      setSelected(null);
      setSelectedId(null);
      setLiveNodeRuns([]);
      return;
    }
    if (
      brief.verification_result !== selected.verification_result
      || brief.evaluable !== selected.evaluable
      || brief.academic_check_status !== selected.academic_check_status
    ) {
      selectCandidate(selectedId);
    }
  }, [candidates, selected, selectedId, selectCandidate, setSelectedId]);

  /** ImportOverlay 透传的字段组增量：合并进预览详情，中栏实时"长出"字段 */
  const handleStructure = useCallback((fileName: string, fields: Record<string, unknown>) => {
    setImportPreview((prev) => {
      // 首个分节到达且当前没在预览态：用文件名初始化预览
      if (!prev || prev.id !== `importing-${fileName}`) {
        return mergePreviewFields(createImportPreview(fileName), fields);
      }
      return mergePreviewFields(prev, fields);
    });
  }, []);

  const handleEvaluate = async () => {
    if (!selectedId) return;
    const startedId = selectedId;
    const controller = new AbortController();
    evalAbortRef.current?.abort();
    evalAbortRef.current = controller;
    setEvaluating(true);
    // 重新评估必须清空上一轮运行记录，否则运行过程会一直显示旧 run 的完成态
    setLiveNodeRuns([]);
    const isStale = () => currentIdRef.current !== startedId;
    try {
      const resp = await api.candidates.evaluateSSE(selectedId, controller.signal);
      if (!resp.ok) {
        if (resp.status === 409) {
          await selectCandidate(selectedId);
          return;
        }
        const error = await resp.json().catch(() => null) as { detail?: string } | null;
        throw new Error(error?.detail || t("评估请求失败"));
      }
      // 后端已创建新的 evaluation_run：立即刷新详情，让 persistedRuns 指向新 run
      const fresh = await api.candidates.get(selectedId).catch(() => null);
      if (fresh && !isStale()) setSelected(fresh);
      if (isStale()) return;
      setEvaluating(true);
      for await (const event of parseSSE(resp, controller.signal)) {
        if (isStale()) break; // 用户切走，停止处理 SSE
        const e = event as { type: string; result?: unknown } & Partial<EvaluationNodeRun>;
        if (e.type === "node" && e.node && e.phase && e.status) {
          const nodeRun: EvaluationNodeRun = {
            node: e.node,
            label: e.label,
            phase: e.phase,
            status: e.status,
            message: e.message || t("已完成"),
          };
          setLiveNodeRuns((runs) => [...runs.filter((run) => run.node !== nodeRun.node), nodeRun]);
        }
        if (e.type === "result") {
          await selectCandidate(selectedId);
        }
      }
    } catch (err) {
      if (controller.signal.aborted) return; // 主动取消不算错误
      console.error("评估失败", err);
    } finally {
      if (isStale()) return; // 用户已切走，不回写
      const detail = await api.candidates.get(selectedId).catch(() => null);
      if (detail && !isStale()) {
        setSelected(detail);
        setLiveNodeRuns(detail.evaluation_run?.node_runs || []);
        setEvaluating(detail.evaluation_run?.status === "running");
      }
    }
  };

  // 批量评估：最多 5 个并发跑（后端每个候选人各自一条 evaluation_run 线程，
  // 互不冲突），多的排队等槽位释放。不展开单条进度，整体跑完刷新列表。
  const handleEvaluateBatch = useCallback(async (ids: string[]) => {
    if (!ids.length) return;
    setEvaluating(true);
    const CONCURRENCY = 5;
    const queue = [...ids];
    const runOne = async (id: string) => {
      try {
        const resp = await api.candidates.evaluateSSE(id);
        if (!resp.ok) return; // 单条跳过（409 已在跑 / 门禁未通过）
        for await (const _event of parseSSE(resp)) { /* 跑完即可 */ }
      } catch (err) {
        console.error("批量评估单条失败", id, err);
      }
      // 每条完成就刷列表，让左栏状态实时更新
      await loadCandidates();
    };
    // 并发池：每当一个槽位空出，从 queue 取下一条
    const workers: Promise<void>[] = [];
    for (let i = 0; i < Math.min(CONCURRENCY, queue.length); i++) {
      workers.push((async () => {
        while (queue.length > 0) {
          const id = queue.shift();
          if (id) await runOne(id);
        }
      })());
    }
    try {
      await Promise.all(workers);
      if (selectedId) await selectCandidate(selectedId);
    } finally {
      setEvaluating(false);
    }
  }, [loadCandidates, selectCandidate, selectedId]);

  // 移出候选人：
  // - 已评估 → dismiss（软移出，数据保留在人才库）
  // - 未评估 → delete（物理删除）
  const handleDelete = useCallback(async (id: string, evaluated: boolean) => {
    try {
      if (evaluated) {
        await api.candidates.dismiss(id);
      } else {
        await api.candidates.delete(id);
      }
      if (selectedId === id) {
        setSelected(null);
        setSelectedId(null);
        setLiveNodeRuns([]);
      }
      await loadCandidates();
    } catch (err) {
      console.error("移出候选人失败", err);
    }
  }, [selectedId, loadCandidates, setSelectedId]);

  return (
    <div>
      <PageToolbar
        title={t("简历评估")}
        subtitle={t("能力结构、Track 推荐与论文核验")}
        center={
          <CandidateMetaDropdown candidate={selected} busy={evaluating} />
        }
        right={
          <>
            {evaluating ? (
              <StatusChip tone="warning" size="md" icon="pending">{t("评估中")}</StatusChip>
            ) : selected?.verification_result === "running" ? (
              <StatusChip tone="primary" size="md">{t("论文核验中")}</StatusChip>
            ) : selected?.verification_result === "verified" ? (
              <StatusChip tone="success" size="md" icon="check_circle">{t("核验通过")}</StatusChip>
            ) : selected?.verification_result === "rejected" ? (
              <StatusChip tone="error" size="md" icon="gpp_maybe">{t("核验不通过")}</StatusChip>
            ) : selected?.verification_result === "needs_review" ? (
              <StatusChip tone="warning" size="md" icon="help">{t("待人工核验")}</StatusChip>
            ) : selected ? (
              <StatusChip tone="warning" size="md">{t("待核验")}</StatusChip>
            ) : (
              <StatusChip tone="neutral" size="md">{t("空闲")}</StatusChip>
            )}
            {evaluating ? (
              <span className="inline-flex items-center justify-center w-10 h-10" title={t("评估中")}>
                <LoadingIndicator size={20} color="text-primary" />
              </span>
            ) : (
              <Button
                variant="filled"
                icon="bolt"
                onClick={handleEvaluate}
                disabled={!selectedId || !selected?.evaluable}
                title={selected?.evaluable ? t("开始评估") : t("核验未完成或有待核验论文")}
              >
                {selected?.evaluation ? t("重新评估") : t("开始评估")}
              </Button>
            )}
          </>
        }
      />

      <div className="app-workspace-frame grid grid-cols-[280px_minmax(0,1fr)_minmax(0,1.2fr)] gap-4">
        {/* 左栏：候选人队列 */}
        <CandidateQueue
          candidates={candidates}
          selectedId={selectedId}
          onSelect={selectCandidate}
          onDelete={handleDelete}
          onImport={() => setShowImport(true)}
          onEvaluateBatch={handleEvaluateBatch}
          runningCard={showImport ? <ImportOverlay onCandidate={loadCandidates} onStructure={handleStructure} onClose={() => {
            setShowImport(false);
            setImportPreview(null);
            loadCandidates();
            api.candidates.list().then((list) => {
              if (list.length > 0) selectCandidate(list[0].id);
            }).catch(() => {});
          }} /> : null}
        />

        {/* 中栏：简历内容（容器不滚，内部模块卡各自滚动） */}
        <Card variant="filled" className="min-h-0 overflow-hidden p-5">
          {loading ? (
            <div className="flex items-center justify-center h-full">
              <LoadingIndicator size={32} label={t("加载中…")} />
            </div>
          ) : importPreview ? (
            <ResumeContent key={importPreview.id} detail={importPreview} />
          ) : selected ? (
            <ResumeContent key={selected.id} detail={selected} onReviewed={refreshSelectedSilently} />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center gap-2">
              <Icon name="description" size={40} className="text-on-surface-variant" />
              <p className="text-title">{t("从左侧选择一位候选人")}</p>
              <p className="text-body-sm text-on-surface-variant">{t("导入简历后，候选人将出现在队列中")}</p>
            </div>
          )}
        </Card>

        {/* 右栏：评估结果与运行过程 */}
        <Card variant="filled" className="min-h-0 overflow-hidden p-5">
          {selected ? (
            <EvaluationWorkspace
              key={selected.id}
              candidateId={selected.id}
              candidatePersonId={selected.person_id}
              evaluation={selected.evaluation}
              evaluationRun={selected.evaluation_run}
              academicReport={selected.academic_report}
              graph={selected.evaluation_graph}
              liveNodeRuns={liveNodeRuns}
              evaluating={evaluating}
            />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center gap-2">
              <Icon name="fact_check" size={40} className="text-on-surface-variant" />
              <p className="text-title">{t("评估结果区")}</p>
              <p className="text-body-sm text-on-surface-variant">{t("选择候选人并评估后，能力评分与 Track 推荐将显示在此")}</p>
            </div>
          )}
        </Card>
      </div>

    </div>
  );
}
