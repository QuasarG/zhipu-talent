import { useState } from "react";
import type { CandidateBrief } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import SearchField from "@/components/ui/SearchField";
import SegmentedButtons from "@/components/ui/SegmentedButtons";
import { StatusChip } from "@/components/ui/Chip";
import Icon from "@/components/ui/Icon";
import { cn } from "@/lib/cn";

interface Props {
  candidates: CandidateBrief[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string, evaluated: boolean) => void | Promise<void>;
  onImport: () => void;
}

type Filter = "pending" | "completed" | "all";

function classifyCandidate(c: CandidateBrief): Filter {
  if (c.engagement_status && c.engagement_status !== "newly_admitted") return "completed";
  if (c.group === "pending") return "pending";
  return "completed";
}

export default function CandidateQueue({ candidates, selectedId, onSelect, onDelete, onImport }: Props) {
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  // 删除二次确认：记录正在确认删除的候选人 id，null = 未进入确认态
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

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
                onClick={() => !confirming && onSelect(c.id)}
                onKeyDown={(e) => {
                  if (!confirming && (e.key === "Enter" || e.key === " ")) {
                    e.preventDefault();
                    onSelect(c.id);
                  }
                }}
                className={cn(
                  "group relative flex items-start gap-3 p-3 rounded-md text-left cursor-pointer transition-colors duration-150 outline-none",
                  "focus-visible:ring-2 focus-visible:ring-primary",
                  confirming ? "bg-error-container" : active ? "bg-secondary-container" : "bg-transparent hover:bg-surface-low"
                )}
              >
                {/* 头像色块：姓名首字 */}
                <span className="flex items-center justify-center w-9 h-9 rounded-full bg-primary-container text-on-primary-container text-label shrink-0">
                  {(c.name || c.id).slice(0, 1)}
                </span>
                <span className="flex-1 min-w-0">
                  <span className="flex items-center justify-between gap-2">
                    <span className="text-title truncate">{c.name || c.id}</span>
                    <StatusChip tone={done ? "success" : "warning"} className="shrink-0">
                      {done ? "已完成" : "待评估"}
                    </StatusChip>
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

                {/* hover 显示的删除按钮（不在确认态时才浮现） */}
                {!confirming && (
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

      <Button variant="tonal" icon="upload" onClick={onImport} className="w-full">
        导入简历
      </Button>
    </Card>
  );
}
