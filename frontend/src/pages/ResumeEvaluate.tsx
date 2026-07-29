import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import { parseSSE } from "@/lib/api";
import type { CandidateBrief, CandidateDetail } from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import { IconButton } from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/Chip";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import CandidateQueue from "@/features/resume/CandidateQueue";
import ResumeContent from "@/features/resume/ResumeContent";
import ScoreOverview from "@/features/resume/ScoreOverview";
import ImportOverlay from "@/features/resume/ImportOverlay";
import CandidateMetaDropdown from "@/features/resume/CandidateMetaDropdown";

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
      }
      await loadCandidates();
    } catch (err) {
      console.error("移出候选人失败", err);
    }
  }, [selectedId, loadCandidates]);

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
            ) : selected ? (
              <StatusChip tone="success" size="md" icon="check_circle">已就绪</StatusChip>
            ) : (
              <StatusChip tone="neutral" size="md">空闲</StatusChip>
            )}
            {evaluating ? (
              <span className="inline-flex items-center justify-center w-10 h-10" title="评估中">
                <LoadingIndicator size={20} color="text-primary" />
              </span>
            ) : (
              <IconButton
                icon="refresh"
                variant="tonal"
                onClick={handleEvaluate}
                disabled={!selectedId}
                title="重新评估"
              />
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
          ) : selected ? (
            <ResumeContent detail={selected} />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center gap-2">
              <Icon name="description" size={40} className="text-on-surface-variant" />
              <p className="text-title">从左侧选择一位候选人</p>
              <p className="text-body-sm text-on-surface-variant">导入简历后，候选人将出现在队列中</p>
            </div>
          )}
        </Card>

        {/* 右栏：评估结果 */}
        <Card variant="filled" className="min-h-0 overflow-y-auto p-5">
          {selected?.evaluation ? (
            <ScoreOverview evaluation={selected.evaluation} />
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-center gap-2">
              <Icon name="fact_check" size={40} className="text-on-surface-variant" />
              <p className="text-title">评估结果区</p>
              <p className="text-body-sm text-on-surface-variant">选择候选人并评估后，能力评分与 Track 推荐将显示在此</p>
            </div>
          )}
        </Card>
      </div>

      {showImport && <ImportOverlay onClose={() => { setShowImport(false); loadCandidates(); }} />}
    </div>
  );
}
