import { useState, useEffect, useRef, useCallback } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";
import Icon from "@/components/ui/Icon";
import type { NotificationItem } from "@/lib/types";

export default function NotificationBell({ className }: { className?: string }) {
  const { t } = useI18n();
  const [unreadCount, setUnreadCount] = useState(0);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  const refresh = useCallback(() => {
    api.notifications
      .list()
      .then((data) => {
        setUnreadCount(data.unread_count);
        setItems(data.items);
      })
      .catch(() => {});
  }, []);

  // 轮询未读数（30s），打开面板时实时刷新
  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 30_000);
    return () => clearInterval(timer);
  }, [refresh]);

  // 点击外部关闭面板
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        panelRef.current?.contains(e.target as Node) ||
        btnRef.current?.contains(e.target as Node)
      )
        return;
      setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const handleMarkRead = async (id: string) => {
    await api.notifications.markRead(id).catch(() => {});
    refresh();
  };

  const handleMarkAllRead = async () => {
    await api.notifications.markAllRead().catch(() => {});
    refresh();
  };

  return (
    <div className={cn("relative flex items-center justify-center", className)}>
      <button
        ref={btnRef}
        onClick={() => {
          setOpen(!open);
          if (!open) refresh();
        }}
        className="relative state-layer w-10 h-10 rounded-full text-on-surface-variant flex items-center justify-center cursor-pointer hover:bg-surface-high"
        title={t("通知")}
      >
        <Icon name="notifications" size={20} />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] rounded-full bg-error text-white text-[10px] font-bold flex items-center justify-center px-1">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div
          ref={panelRef}
          className="absolute bottom-0 left-full ml-2 w-80 max-h-96 overflow-y-auto rounded-2xl bg-surface shadow-lg border border-outline-variant z-50"
        >
          <div className="flex items-center justify-between px-4 py-3 border-b border-outline-variant">
            <span className="text-title-small font-semibold">{t("通知")}</span>
            {unreadCount > 0 && (
              <button
                onClick={handleMarkAllRead}
                className="text-label text-primary cursor-pointer hover:underline"
              >
                {t("全部已读")}
              </button>
            )}
          </div>
          {items.length === 0 ? (
            <div className="px-4 py-8 text-center text-body-medium text-on-surface-variant">
              {t("暂无通知")}
            </div>
          ) : (
            <ul>
              {items.map((n) => (
                <li
                  key={n.id}
                  className={`px-4 py-3 border-b border-outline-variant last:border-b-0 cursor-pointer hover:bg-surface-container ${n.status === "unread" ? "bg-primary-container/30" : ""}`}
                  onClick={() => n.status === "unread" && handleMarkRead(n.id)}
                >
                  <div className="flex items-start gap-2">
                    {n.status === "unread" && (
                      <span className="mt-1.5 w-2 h-2 rounded-full bg-primary shrink-0" />
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="text-body-medium font-medium truncate">{n.title}</div>
                      {n.body && (
                        <div className="text-body-small text-on-surface-variant mt-0.5 line-clamp-3">
                          {n.body}
                        </div>
                      )}
                      <div className="text-label text-on-surface-variant mt-1">
                        {n.created_at.slice(0, 16).replace("T", " ")}
                      </div>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
