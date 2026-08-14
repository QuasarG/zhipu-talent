import { useState } from "react";
import type { ChatConversation } from "@/lib/types";
import Button, { IconButton } from "@/components/ui/Button";
import HelpDialog from "./HelpDialog";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

interface Props {
  conversations: ChatConversation[];
  currentId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
}

/** 相对时间：分钟内显示"刚刚"，其后逐级退化到日期。
 * 后端 SQLite 存的是 UTC 时间（YYYY-MM-DD HH:MM:SS 无时区后缀），
 * 补 Z 后缀让 JS 按 UTC 解析，避免 8 小时偏差。 */
function relativeTime(
  iso: string,
  t: (key: string, params?: Record<string, string | number>) => string
): string {
  if (!iso) return "";
  const normalized = iso.includes("T") ? iso : iso.replace(" ", "T");
  const time = new Date(normalized.endsWith("Z") ? normalized : normalized + "Z").getTime();
  if (Number.isNaN(time)) return "";
  const diff = Date.now() - time;
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return t("刚刚");
  if (minutes < 60) return t("{n} 分钟前", { n: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("{n} 小时前", { n: hours });
  const days = Math.floor(hours / 24);
  if (days < 7) return t("{n} 天前", { n: days });
  return new Date(time).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

/** 会话侧栏：列表 + 新建/重命名/删除 */
export default function ChatSidebar({ conversations, currentId, onSelect, onCreate, onRename, onDelete }: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  // 删除二次确认：第一次点击进入确认态，再点一次才真删（对齐候选队列惯例）
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [showHelp, setShowHelp] = useState(false);
  const { t } = useI18n();

  const commitRename = (id: string) => {
    const title = draft.trim();
    if (title) onRename(id, title);
    setEditingId(null);
  };

  const handleDelete = (id: string) => {
    if (confirmingId === id) {
      setConfirmingId(null);
      onDelete(id);
      return;
    }
    setConfirmingId(id);
    setTimeout(() => setConfirmingId((cur) => (cur === id ? null : cur)), 3000);
  };

  return (
    <div className="w-60 shrink-0 flex flex-col gap-2 min-h-0">
      <Button variant="tonal" icon="add" className="w-full shrink-0" onClick={onCreate}>
        {t("新建对话")}
      </Button>
      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-1 pr-0.5">
        {conversations.length === 0 ? (
          <div className="text-center py-8 text-body-sm text-on-surface-variant">{t("还没有会话")}</div>
        ) : (
          conversations.map((conv) => {
            const active = conv.id === currentId;
            return (
              <div
                key={conv.id}
                onClick={() => onSelect(conv.id)}
                className={cn(
                  "group relative px-3 py-2.5 rounded-md cursor-pointer transition-colors duration-150",
                  active
                    ? "bg-secondary-container shadow-[inset_0_0_0_2px_var(--color-primary)]"
                    : "hover:bg-surface-low"
                )}
              >
                {editingId === conv.id ? (
                  <input
                    autoFocus
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    onBlur={() => commitRename(conv.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") commitRename(conv.id);
                      if (e.key === "Escape") setEditingId(null);
                    }}
                    className="w-full h-7 px-2 rounded-sm border border-outline-variant bg-surface-lowest text-body-sm text-on-surface outline-none focus:outline-2 focus:outline-primary"
                  />
                ) : (
                  <>
                    <p className="text-body-sm font-medium text-on-surface truncate pr-12">
                      {conv.title || t("新对话")}
                    </p>
                    <p className="text-label text-on-surface-variant mt-0.5">{relativeTime(conv.updated_at, t)}</p>
                    <div className="absolute right-1 top-1/2 -translate-y-1/2 hidden group-hover:flex items-center">
                      {confirmingId === conv.id ? (
                        <button
                          type="button"
                          title={t("再点一次确认删除")}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDelete(conv.id);
                          }}
                          className="px-3 h-8 rounded-full text-label font-medium text-error hover:bg-error-container"
                        >
                          {t("确认删除")}
                        </button>
                      ) : (
                        <>
                          <IconButton
                            icon="edit"
                            size={16}
                            className="w-8 h-8"
                            title={t("重命名")}
                            onClick={(e) => {
                              e.stopPropagation();
                              setDraft(conv.title || "");
                              setEditingId(conv.id);
                            }}
                          />
                          <IconButton
                            icon="delete"
                            size={16}
                            className="w-8 h-8"
                            title={t("删除会话")}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDelete(conv.id);
                            }}
                          />
                        </>
                      )}
                    </div>
                  </>
                )}
              </div>
            );
          })
        )}
      </div>
      <Button data-tour="help-btn" variant="outlined" icon="help" className="w-full shrink-0" onClick={() => setShowHelp(true)}>
        {t("使用说明")}
      </Button>
      {showHelp && <HelpDialog onClose={() => setShowHelp(false)} />}
    </div>
  );
}
