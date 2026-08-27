import { useState } from "react";
import type { GrillSessionSummary } from "@/lib/types";
import Button, { IconButton } from "@/components/ui/Button";
import Icon from "@/components/ui/Icon";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/cn";

/** 相对时间：分钟内显示「刚刚」，逐级退化到日期；后端存 UTC ISO，带 Z 直接解析 */
function relativeTime(iso: string, t: (key: string, params?: Record<string, string | number>) => string): string {
  if (!iso) return "";
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return "";
  const minutes = Math.floor((Date.now() - time) / 60000);
  if (minutes < 1) return t("刚刚");
  if (minutes < 60) return t("{n} 分钟前", { n: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("{n} 小时前", { n: hours });
  const days = Math.floor(hours / 24);
  if (days < 7) return t("{n} 天前", { n: days });
  return new Date(time).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

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
  const { t } = useI18n();
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
        {t("新建对话")}
      </Button>

      <div className="flex flex-1 min-h-0 flex-col gap-1 overflow-y-auto pr-0.5">
        {sessions.length === 0 ? (
          <div className="py-8 text-center text-body-sm text-on-surface-variant">{t("还没有会话")}</div>
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
                {managing && (
                  <span
                    className={cn(
                      "absolute left-3 top-1/2 flex h-4 w-4 -translate-y-1/2 items-center justify-center rounded-sm border",
                      checked ? "border-primary bg-primary text-on-primary" : "border-outline"
                    )}
                  >
                    {checked && <Icon name="check" size={13} />}
                  </span>
                )}
                <p
                  className={cn(
                    "truncate text-body-sm font-medium text-on-surface",
                    managing ? "pl-6" : "pr-10"
                  )}
                  title={s.title}
                >
                  {s.title}
                </p>
                <p className={cn("mt-0.5 truncate text-label text-on-surface-variant", managing && "pl-6")}>
                  {t(s.status)} · {relativeTime(s.updated_at, t)}
                </p>
                {!managing && (
                  <div className="absolute right-1 top-1/2 hidden -translate-y-1/2 items-center group-hover:flex group-focus-within:flex">
                    {confirmingId === s.session_id ? (
                      <button
                        type="button"
                        title={t("再点一次确认删除")}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteOne(s.session_id);
                        }}
                        className="h-8 rounded-full px-3 text-label font-medium text-error hover:bg-error-container focus-visible:outline-2 focus-visible:outline-primary"
                      >
                        {t("确认删除")}
                      </button>
                    ) : (
                      <IconButton
                        icon="delete"
                        size={16}
                        className="h-8 w-8"
                        title={t("删除会话")}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteOne(s.session_id);
                        }}
                      />
                    )}
                  </div>
                )}
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
            {allSelected ? t("全不选") : t("全选")}
          </Button>
          <Button
            variant="text"
            className={cn("h-8 px-3", confirmingBatch && "text-error")}
            disabled={!selected.size}
            onClick={handleBatchDelete}
          >
            {confirmingBatch ? t("确认删除 {n} 个？", { n: selected.size }) : t("删除选中（{n}）", { n: selected.size })}
          </Button>
          <Button variant="text" className="h-8 px-3" onClick={exitManage}>
            {t("取消")}
          </Button>
        </div>
      ) : (
        sessions.length > 0 && (
          <Button variant="outlined" icon="checklist" className="w-full shrink-0" onClick={() => setManaging(true)}>
            {t("批量管理")}
          </Button>
        )
      )}
    </div>
  );
}
