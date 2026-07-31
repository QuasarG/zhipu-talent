import { useState, useEffect, useCallback } from "react";
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

/** 把导入预览的字段增量合并进详情：列表追加去重，单值取首个非空 */
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
    const incoming = fields[key];
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
  /** 导入解析中的临时预览详情：中栏实时"长出"字段，落库后被正式 selected 取代 */
  const [importPreview, setImportPreview] = useState<CandidateDetail | null>(null);

  const loadCandidates = useCallback(async () => {
    try {
      const list = await api.candidates.list();
      setCandidates(list);
    } catch (err) {
      console.error("加载候选人失败", err);
    }
  }, []);

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
    setSelectedId(id);
    setLoading(true);
    try {
      const detail = await api.candidates.get(id);
      setSelected(detail);
      setLiveNodeRuns(detail.evaluation_run?.node_runs || []);
      setEvaluating(detail.evaluation_run?.status === "running");
    } catch (err) {
      console.error("加载详情失败", err);
    } finally {
      setLoading(false);
    }
  }, [setSelectedId]);

  useEffect(() => {
    if (!selectedId || selected || !candidates.some((candidate) => candidate.id === selectedId)) return;
    selectCandidate(selectedId);
  }, [candidates, selected, selectedId, selectCandidate]);

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

  /** ImportOverlay 透传的分节增量：合并进预览详情，中栏实时"长出"字段 */
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
    setEvaluating(true);
    // 重新评估必须清空上一轮运行记录，否则运行过程会一直显示旧 run 的完成态
    setLiveNodeRuns([]);
    try {
      const resp = await api.candidates.evaluateSSE(selectedId);
      if (!resp.ok) {
        if (resp.status === 409) {
          await selectCandidate(selectedId);
          return;
        }
        const error = await resp.json().catch(() => null) as { detail?: string } | null;
        throw new Error(error?.detail || "评估请求失败");
      }
      // 后端已创建新的 evaluation_run：立即刷新详情，让 persistedRuns 指向新 run
      const fresh = await api.candidates.get(selectedId).catch(() => null);
      if (fresh) setSelected(fresh);
      setEvaluating(true);
      for await (const event of parseSSE(resp)) {
        const e = event as { type: string; result?: unknown } & Partial<EvaluationNodeRun>;
        if (e.type === "node" && e.node && e.phase && e.status) {
          const nodeRun: EvaluationNodeRun = {
            node: e.node,
            label: e.label,
            phase: e.phase,
            status: e.status,
            message: e.message || "已完成",
          };
          setLiveNodeRuns((runs) => [...runs.filter((run) => run.node !== nodeRun.node), nodeRun]);
        }
        if (e.type === "result") {
          // 重新加载详情
          await selectCandidate(selectedId);
        }
      }
    } catch (err) {
      console.error("评估失败", err);
    } finally {
      const detail = await api.candidates.get(selectedId).catch(() => null);
      if (detail) {
        setSelected(detail);
        setLiveNodeRuns(detail.evaluation_run?.node_runs || []);
        setEvaluating(detail.evaluation_run?.status === "running");
      }
    }
  };

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
        title="简历评估"
        subtitle="能力结构、Track 推荐与论文核验"
        center={
          <CandidateMetaDropdown candidate={selected} busy={evaluating} />
        }
        right={
          <>
            {evaluating ? (
              <StatusChip tone="warning" size="md" icon="pending">评估中</StatusChip>
            ) : selected?.verification_result === "running" ? (
              <StatusChip tone="primary" size="md">论文核验中</StatusChip>
            ) : selected?.verification_result === "verified" ? (
              <StatusChip tone="success" size="md" icon="check_circle">核验通过</StatusChip>
            ) : selected?.verification_result === "rejected" ? (
              <StatusChip tone="error" size="md" icon="gpp_maybe">核验不通过</StatusChip>
            ) : selected?.verification_result === "needs_review" ? (
              <StatusChip tone="warning" size="md" icon="help">待人工核验</StatusChip>
            ) : selected ? (
              <StatusChip tone="warning" size="md">待核验</StatusChip>
            ) : (
              <StatusChip tone="neutral" size="md">空闲</StatusChip>
            )}
            {evaluating ? (
              <span className="inline-flex items-center justify-center w-10 h-10" title="评估中">
                <LoadingIndicator size={20} color="text-primary" />
              </span>
            ) : (
              <Button
                variant="filled"
                icon="bolt"
                onClick={handleEvaluate}
                disabled={!selectedId || !selected?.evaluable}
                title={selected?.evaluable ? "开始评估" : "核验未完成或有待核验论文"}
              >
                {selected?.evaluation ? "重新评估" : "开始评估"}
              </Button>
            )}
          </>
        }
      />

      <div className="grid grid-cols-[280px_minmax(0,1fr)_minmax(0,1.2fr)] gap-4 h-[calc(100vh-56px-60px)] min-h-[500px]">
        {/* 左栏：候选人队列 */}
        <CandidateQueue
          candidates={candidates}
          selectedId={selectedId}
          onSelect={selectCandidate}
          onDelete={handleDelete}
          onImport={() => setShowImport(true)}
        />

        {/* 中栏：简历内容（容器不滚，内部模块卡各自滚动） */}
        <Card variant="filled" className="min-h-0 overflow-hidden p-5">
          {loading ? (
            <div className="flex items-center justify-center h-full">
              <LoadingIndicator size={32} label="加载中…" />
            </div>
          ) : importPreview ? (
            <ResumeContent key={importPreview.id} detail={importPreview} />
          ) : selected ? (
            <ResumeContent key={selected.id} detail={selected} />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center gap-2">
              <Icon name="description" size={40} className="text-on-surface-variant" />
              <p className="text-title">从左侧选择一位候选人</p>
              <p className="text-body-sm text-on-surface-variant">导入简历后，候选人将出现在队列中</p>
            </div>
          )}
        </Card>

        {/* 右栏：评估结果与运行过程 */}
        <Card variant="filled" className="min-h-0 overflow-hidden p-5">
          {selected ? (
            <EvaluationWorkspace
              key={selected.id}
              candidateId={selected.id}
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
              <p className="text-title">评估结果区</p>
              <p className="text-body-sm text-on-surface-variant">选择候选人并评估后，能力评分与 Track 推荐将显示在此</p>
            </div>
          )}
        </Card>
      </div>

      {showImport && <ImportOverlay onCandidate={loadCandidates} onStructure={handleStructure} onClose={() => {
        setShowImport(false);
        setImportPreview(null);
        loadCandidates();
        // 导入流程已包含论文核验，核验完关闭后刷新列表并选中最新的
        api.candidates.list().then((list) => {
          if (list.length > 0) selectCandidate(list[0].id);
        }).catch(() => {});
      }} />}
    </div>
  );
}
