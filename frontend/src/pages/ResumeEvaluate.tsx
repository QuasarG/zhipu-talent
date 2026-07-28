import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { parseSSE } from "@/lib/api";
import type { CandidateBrief, CandidateDetail } from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import CandidateQueue from "@/features/resume/CandidateQueue";
import ResumeContent from "@/features/resume/ResumeContent";
import ScoreOverview from "@/features/resume/ScoreOverview";
import ImportOverlay from "@/features/resume/ImportOverlay";
import { RefreshCw } from "lucide-react";
import GlassPanel from "@/components/glass/GlassPanel";

export default function ResumeEvaluate() {
  const [candidates, setCandidates] = useState<CandidateBrief[]>([]);
  const [selected, setSelected] = useState<CandidateDetail | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [showImport, setShowImport] = useState(false);

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

  const selectCandidate = useCallback(async (id: string) => {
    setSelectedId(id);
    setLoading(true);
    try {
      const detail = await api.candidates.get(id);
      setSelected(detail);
    } catch (err) {
      console.error("加载详情失败", err);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleEvaluate = async () => {
    if (!selectedId) return;
    setEvaluating(true);
    try {
      const resp = await api.candidates.evaluateSSE(selectedId);
      if (!resp.ok) throw new Error("评估请求失败");
      for await (const event of parseSSE(resp)) {
        const e = event as { type: string; result?: unknown };
        if (e.type === "result") {
          // 重新加载详情
          await selectCandidate(selectedId);
        }
      }
    } catch (err) {
      console.error("评估失败", err);
    } finally {
      setEvaluating(false);
    }
  };

  return (
    <div>
      <PageToolbar
        title="简历评估"
        subtitle="能力结构、Track 推荐与论文核验"
        center={
          <span className="px-4 py-1.5 rounded-full text-sm text-ink-secondary bg-white/35">
            {selected ? `${selected.name} · ${selected.stage || "阶段未知"}` : "未选择候选人"}
          </span>
        }
        right={
          <>
            <span className="text-xs px-2 py-0.5 rounded-full bg-surface-mist text-ink-secondary">
              {evaluating ? "评估中" : selected ? "已就绪" : "空闲"}
            </span>
            <button
              onClick={handleEvaluate}
              disabled={!selectedId || evaluating}
              className="w-9 h-9 rounded-[10px] flex items-center justify-center text-ink-secondary hover:bg-white/35 disabled:opacity-40 transition-colors"
              title="重新评估"
            >
              <RefreshCw size={18} className={evaluating ? "animate-spin" : ""} />
            </button>
          </>
        }
      />

      <div className="grid grid-cols-[260px_1fr_1.4fr] gap-4 h-[calc(100vh-56px-60px)] min-h-[500px]">
        {/* 左栏：候选人队列 */}
        <CandidateQueue
          candidates={candidates}
          selectedId={selectedId}
          onSelect={selectCandidate}
          onImport={() => setShowImport(true)}
        />

        {/* 中栏：简历内容 */}
        <div className="overflow-y-auto p-4 rounded-[14px]">
          {loading ? (
            <div className="flex items-center justify-center h-full text-ink-secondary">加载中…</div>
          ) : selected ? (
            <ResumeContent detail={selected} />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center gap-2 text-ink-secondary">
              <p className="text-base">从左侧选择一位候选人</p>
              <p className="text-xs text-ink-muted">导入简历后，候选人将出现在队列中</p>
            </div>
          )}
        </div>

        {/* 右栏：评估结果 */}
        <div className="overflow-y-auto p-4 rounded-[14px]">
          {selected?.evaluation ? (
            <ScoreOverview evaluation={selected.evaluation} />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center gap-2 text-ink-secondary">
              <p className="text-base">评估结果区</p>
              <p className="text-xs text-ink-muted">选择候选人并评估后，能力评分与 Track 推荐将显示在此</p>
            </div>
          )}
        </div>
      </div>

      {showImport && <ImportOverlay onClose={() => { setShowImport(false); loadCandidates(); }} />}
    </div>
  );
}
