import { useState } from "react";
import type { GrillSessionSummary } from "@/lib/types";
import Button, { IconButton } from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/Chip";
import { cn } from "@/lib/cn";

/** 相对时间：分钟内显示「刚刚」，逐级退化到日期；后端存 UTC ISO，带 Z 直接解析 */
function relativeTime(iso: string): string {
  if (!iso) return "";
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return "";
  const minutes = Math.floor((Date.now() - time) / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} 天前`;
  return new Date(time).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

const STATUS_TONE: Record<string, "neutral" | "primary" | "success"> = {
  进行中: "neutral",
  已澄清: "primary",
  已交付: "success",
};

interface Props {
  sessions: GrillSessionSummary[];
  currentId: string;
  busy: boolean;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: (ids: string[]) => void;
}

/** 会话侧栏：新建/切换 + 悬浮删除（二次确认）+ 多选批量删除 */
export default function SessionSidebar({ sessions, currentId, busy, onSelect, onCreate, onDelete }: Props) {
  // 单个删除二次确认：第一次点进确认态，3s 内再点才真删（参考项目惯例）
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [managing, setManaging] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmingBatch, setConfirmingBatch] = useState(false);

  const handleDeleteOne = (id: string) => {
    if (confirmingId === id) {
      setConfirmingId(null);
      onDelete([id]);
      return;
    }
    setConfirmingId(id);
    setTimeout(() => setConfirmingId((cur) => (cur === id ? null : cur)), 3000);
  };

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const exitManage = () => {
    setManaging(false);
    setSelected(new Set());
    setConfirmingBatch(false);
  };

  const handleBatchDelete = () => {
    if (!selected.size) return;
    if (confirmingBatch) {
      onDelete([...selected]);
      exitManage();
      return;
    }
    setConfirmingBatch(true);
    setTimeout(() => setConfirmingBatch(false), 3000);
  };

  const allSelected = sessions.length > 0 && selected.size === sessions.length;

  return (
    <div className="flex w-60 shrink-0 flex-col gap-2 min-h-0">
      <Button variant="tonal" icon="add" className="w-full shrink-0" disabled={busy} onClick={onCreate}>
        新建对话
      </Button>

      <div className="flex flex-1 min-h-0 flex-col gap-1 overflow-y-auto pr-0.5">
        {sessions.length === 0 ? (
          <div className="py-8 text-center text-body-sm text-on-surface-variant">还没有会话</div>
        ) : (
          sessions.map((s) => {
            const active = s.session_id === currentId;
            const checked = selected.has(s.session_id);
            return (
              <div
                key={s.session_id}
                onClick={() => (managing ? toggle(s.session_id) : !busy && onSelect(s.session_id))}
                className={cn(
                  "group relative px-3 py-2.5 rounded-md transition-colors duration-150",
                  managing || !busy ? "cursor-pointer" : "cursor-default",
                  active && !managing
                    ? "bg-secondary-container shadow-[inset_0_0_0_2px_var(--color-primary)]"
                    : checked
                      ? "bg-primary-container/50"
                      : "hover:bg-surface-low"
                )}
              >
                <div className="flex items-center gap-2">
                  {managing && (
                    <span
                      className={cn(
                        "flex h-4 w-4 shrink-0 items-center justify-center rounded-sm border",
                        checked ? "border-primary bg-primary text-on-primary" : "border-outline"
                      )}
                    >
                      {checked && "✓"}
                    </span>
                  )}
                  {/* 删除按钮绝对定位悬浮，不进文档流，避免 hover 撑高条目 */}
                  <p className={cn("flex-1 min-w-0 truncate text-body-sm font-medium text-on-surface", !managing && "pr-7")}>
                    {s.title}
                  </p>
                  {!managing && confirmingId === s.session_id ? (
                    <button
                      type="button"
                      title="再点一次确认删除"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteOne(s.session_id);
                      }}
                      className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full px-2 h-6 text-label font-medium text-error bg-surface-lowest hover:bg-error-container"
                    >
                      确认删除
                    </button>
                  ) : (
                    !managing && (
                      <IconButton
                        icon="delete"
                        size={16}
                        className="absolute right-2 top-1/2 -translate-y-1/2 hidden h-6 w-6 shrink-0 group-hover:flex"
                        title="删除会话"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteOne(s.session_id);
                        }}
                      />
                    )
                  )}
                </div>
                <div className="mt-1 flex items-center justify-between gap-2">
                  <StatusChip tone={STATUS_TONE[s.status] || "neutral"} className="h-5 px-2">
                    {s.status}
                  </StatusChip>
                  <span className="shrink-0 text-label text-on-surface-variant">
                    {relativeTime(s.updated_at)}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>

      {managing ? (
        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="text"
            className="h-8 px-3"
            onClick={() => setSelected(allSelected ? new Set() : new Set(sessions.map((s) => s.session_id)))}
          >
            {allSelected ? "全不选" : "全选"}
          </Button>
          <Button
            variant="text"
            className={cn("h-8 px-3", confirmingBatch && "text-error")}
            disabled={!selected.size}
            onClick={handleBatchDelete}
          >
            {confirmingBatch ? `确认删除 ${selected.size} 个？` : `删除选中（${selected.size}）`}
          </Button>
          <Button variant="text" className="h-8 px-3" onClick={exitManage}>
            取消
          </Button>
        </div>
      ) : (
        sessions.length > 0 && (
          <Button variant="outlined" icon="checklist" className="w-full shrink-0" onClick={() => setManaging(true)}>
            批量管理
          </Button>
        )
      )}
    </div>
  );
}
