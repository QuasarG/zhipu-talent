import { useState } from "react";
import { useSessionState } from "@/lib/sessionState";
import type { CandidateBrief } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import SearchField from "@/components/ui/SearchField";
import SegmentedButtons from "@/components/ui/SegmentedButtons";
import { StatusChip } from "@/components/ui/Chip";
import Icon from "@/components/ui/Icon";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import { cn } from "@/lib/cn";

interface Props {
  candidates: CandidateBrief[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string, evaluated: boolean) => void | Promise<void>;
  onImport: () => void;
  onEvaluateBatch?: (ids: string[]) => void | Promise<void>;
}

type Filter = "pending" | "completed" | "all";

function classifyCandidate(c: CandidateBrief): Filter {
  if (c.engagement_status && c.engagement_status !== "newly_admitted") return "completed";
  if (c.evaluation_status === "completed" || c.evaluation_status === "failed") return "completed";
  if (c.group === "pending") return "pending";
  return "completed";
}

export default function CandidateQueue({ candidates, selectedId, onSelect, onDelete, onImport, onEvaluateBatch }: Props) {
  const [filter, setFilter] = useSessionState<Filter>("resume-evaluate.queue-filter", "all");
  const [search, setSearch] = useSessionState("resume-evaluate.queue-search", "");
  // 删除二次确认：记录正在确认删除的候选人 id，null = 未进入确认态
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  // 批量操作态：进入后状态标签隐藏，卡片变为 checkbox
  const [batchMode, setBatchMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [batchEvaluating, setBatchEvaluating] = useState(false);

  const filtered = candidates.filter((c) => {
    if (filter !== "all" && classifyCandidate(c) !== filter) return false;
    if (search) {
      const hay = `${c.name} ${c.role} ${c.stage}`.toLowerCase();
      if (!hay.includes(search.toLowerCase())) return false;
    }
    return true;
  });

  const counts = {
    all: candidates.length,
    pending: candidates.filter((c) => classifyCandidate(c) === "pending").length,
    completed: candidates.filter((c) => classifyCandidate(c) === "completed").length,
  };

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => setSelected(new Set(filtered.map((c) => c.id)));
  const clearAll = () => setSelected(new Set());

  const exitBatch = () => {
    setBatchMode(false);
    setSelected(new Set());
  };

  const batchDelete = async () => {
    if (selected.size === 0 || batchDeleting) return;
    const ids = Array.from(selected);
    setBatchDeleting(true);
    exitBatch(); // 立即退出批量态，删除在后台跑
    try {
      for (const id of ids) {
        const c = candidates.find((it) => it.id === id);
        if (c) await onDelete(c.id, !!c.evaluated);
      }
    } finally {
      setBatchDeleting(false);
    }
  };

  const batchEvaluate = async () => {
    if (selected.size === 0 || batchEvaluating || !onEvaluateBatch) return;
    const ids = Array.from(selected);
    setBatchEvaluating(true);
    exitBatch(); // 立即退出批量态，评估在后台并发跑
    try {
      await onEvaluateBatch(ids);
    } finally {
      setBatchEvaluating(false);
    }
  };

  // 批量当前所选中的「可评估」数量，用于按钮文案与 disable
  const evaluableCount = onEvaluateBatch
    ? Array.from(selected).filter((id) => {
        const c = candidates.find((it) => it.id === id);
        return !!c?.evaluable;
      }).length
    : 0;

  return (
    <Card variant="filled" className="flex flex-col gap-3 p-3 min-h-0">
      <SearchField
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="搜索姓名、学校或方向"
      />

      <SegmentedButtons<Filter>
        className="w-full [&>button]:flex-1"
        options={[
          { value: "all", label: `全部 ${counts.all}` },
          { value: "pending", label: `待评估 ${counts.pending}` },
          { value: "completed", label: `已完成 ${counts.completed}` },
        ]}
        value={filter}
        onChange={setFilter}
      />

      {/* 候选人列表 */}
      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-1">
        {filtered.length === 0 ? (
          <div className="text-center py-10 text-body-sm text-on-surface-variant">无匹配候选人</div>
        ) : (
          filtered.map((c) => {
            const done = classifyCandidate(c) === "completed";
            const active = c.id === selectedId;
            const confirming = confirmingId === c.id;
            // evaluated=true → 已评估移出（软），否则删除（硬）
            const evaluated = !!c.evaluated;
            const checked = selected.has(c.id);
            const doDelete = async () => {
              setDeleting(true);
              try {
                await onDelete(c.id, evaluated);
              } finally {
                setDeleting(false);
                setConfirmingId(null);
              }
            };
            return (
              <div
                key={c.id}
                role="button"
                tabIndex={0}
                onClick={() => batchMode ? toggleSelect(c.id) : (!confirming && onSelect(c.id))}
                onKeyDown={(e) => {
                  if (batchMode && (e.key === "Enter" || e.key === " ")) {
                    e.preventDefault();
                    toggleSelect(c.id);
                  } else if (!confirming && (e.key === "Enter" || e.key === " ")) {
                    e.preventDefault();
                    onSelect(c.id);
                  }
                }}
                className={cn(
                  "group relative flex items-start gap-3 p-3 rounded-md text-left cursor-pointer transition-colors duration-150 outline-none",
                  "focus-visible:ring-2 focus-visible:ring-primary",
                  batchMode && checked ? "bg-secondary-container shadow-[inset_0_0_0_2px_var(--color-primary)]" : confirming ? "bg-error-container" : active ? "bg-secondary-container" : "bg-transparent hover:bg-surface-low"
                )}
              >
                {/* 头像位：批量态替换为 checkbox */}
                {batchMode ? (
                  <span className={cn(
                    "flex items-center justify-center w-9 h-9 rounded-full shrink-0 border-2 transition-colors",
                    checked ? "bg-primary border-primary text-on-primary" : "border-outline text-transparent"
                  )}>
                    {checked && <Icon name="check" size={18} />}
                  </span>
                ) : (
                  <span className="flex items-center justify-center w-9 h-9 rounded-full bg-primary-container text-on-primary-container text-label shrink-0">
                    {(c.name || "?").slice(0, 1)}
                  </span>
                )}
                <span className="flex-1 min-w-0">
                  <span className="flex items-center justify-between gap-2">
                    <span className="text-title truncate">{c.name || "未命名"}</span>
                    {c.evaluation_status === "running" ? (
                      <span className="inline-flex items-center gap-1 text-label text-primary shrink-0">
                        <LoadingIndicator size={14} color="text-primary" />
                        评估中
                      </span>
                    ) : done ? (
                      <StatusChip tone="success" className="shrink-0">已完成</StatusChip>
                    ) : c.verification_result === "running" ? (
                      <span className="inline-flex items-center gap-1 text-label text-primary shrink-0">
                        <LoadingIndicator size={14} color="text-primary" />
                        核验中
                      </span>
                    ) : c.verification_result === "verified" ? (
                      <StatusChip tone="success" className="shrink-0" icon="check_circle">核验通过</StatusChip>
                    ) : c.verification_result === "rejected" ? (
                      <StatusChip tone="error" className="shrink-0" icon="gpp_maybe">核验不通过</StatusChip>
                    ) : c.verification_result === "needs_review" ? (
                      <StatusChip tone="warning" className="shrink-0" icon="help">待人工核验</StatusChip>
                    ) : (
                      <StatusChip tone="warning" className="shrink-0">待核验</StatusChip>
                    )}
                  </span>
                  <span className="block text-body-sm text-on-surface-variant truncate">
                    {c.role || c.stage || "—"}
                  </span>
                  {c.admitted_at && (
                    <span className="block text-label text-on-surface-variant truncate">
                      {c.admitted_at.slice(0, 10)}
                    </span>
                  )}
                  {confirming ? (
                    /* inline 二次确认条：不再 hover 出现，常驻直到 ✓/✗ */
                    <span className="mt-1.5 flex items-center gap-2">
                      <span className="text-body-sm text-on-error-container">
                        {evaluated ? "确认移出？" : "确认删除？"}
                      </span>
                      <button
                        type="button"
                        disabled={deleting}
                        onClick={(e) => { e.stopPropagation(); doDelete(); }}
                        className="state-layer inline-flex items-center justify-center w-6 h-6 rounded-full bg-error text-on-error cursor-pointer disabled:opacity-40"
                        title={evaluated ? "确认移出" : "确认删除"}
                      >
                        <Icon name="check" size={16} />
                      </button>
                      <button
                        type="button"
                        disabled={deleting}
                        onClick={(e) => { e.stopPropagation(); setConfirmingId(null); }}
                        className="state-layer inline-flex items-center justify-center w-6 h-6 rounded-full text-on-error-container cursor-pointer disabled:opacity-40"
                        title="取消"
                      >
                        <Icon name="close" size={16} />
                      </button>
                    </span>
                  ) : null}
                </span>

                {/* hover 显示的删除按钮（不在批量态/确认态时才浮现） */}
                {!batchMode && !confirming && (
                  <span className="absolute top-1.5 right-1.5 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setConfirmingId(c.id); }}
                      className="state-layer inline-flex items-center justify-center w-7 h-7 rounded-full bg-surface-lowest text-on-surface-variant hover:text-error cursor-pointer shadow-sm"
                      title={evaluated ? "移出队列" : "删除"}
                    >
                      <Icon name={evaluated ? "archive" : "delete"} size={16} />
                    </button>
                  </span>
                )}
              </div>
            );
          })
        )}
      </div>

      {batchMode ? (
        <div className="flex items-center gap-1.5">
          <Button variant="text" icon="close" className="shrink-0 h-10 w-10 px-0" disabled={batchDeleting || batchEvaluating}
            onClick={exitBatch} title="退出批量" />
          <Button variant="tonal" className="flex-1 h-10 min-w-0 whitespace-nowrap text-body-sm" disabled={batchDeleting || batchEvaluating}
            onClick={() => (selected.size === filtered.length && filtered.length > 0 ? clearAll() : selectAll())}>
            {selected.size === filtered.length && filtered.length > 0 ? "取消全选" : "全选"}
          </Button>
          {onEvaluateBatch && (
            <Button
              variant="filled"
              disabled={evaluableCount === 0 || batchDeleting || batchEvaluating}
              onClick={batchEvaluate}
              className="flex-1 h-10 min-w-0 whitespace-nowrap text-body-sm"
            >
              {batchEvaluating ? "评估中…" : `评估(${evaluableCount || 0})`}
            </Button>
          )}
          <Button
            variant="filled"
            disabled={selected.size === 0 || batchDeleting || batchEvaluating}
            onClick={batchDelete}
            className="flex-1 h-10 min-w-0 whitespace-nowrap text-body-sm bg-error text-on-error"
          >
            {batchDeleting ? "处理中…" : `移除(${selected.size || 0})`}
          </Button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <Button variant="tonal" icon="upload" onClick={onImport} className="flex-1">
            导入简历
          </Button>
          {candidates.length > 0 && (
            <Button variant="text" icon="checklist" onClick={() => setBatchMode(true)} className="shrink-0">
              批量操作
            </Button>
          )}
        </div>
      )}
    </Card>
  );
}
