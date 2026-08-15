import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import Icon from "@/components/ui/Icon";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import { useI18n } from "@/lib/i18n";

interface HistoryEntry {
  previous_status: string;
  current_status: string;
  changed_by: string;
  note: string;
  changed_at: string | null;
}

interface Props {
  candidateId: string;
  /** 父组件状态变更后递增此 key，时间轴随之重拉 */
  refreshKey: number;
}

const STATUS_LABELS: Record<string, string> = {
  newly_admitted: "已投递",
  screening: "待初筛",
  interviewing: "面试中",
  offer_pending: "待发 Offer",
  offered: "已发 Offer",
  hired: "已入职",
  departed: "已离职",
  rejected: "已淘汰",
  to_contact: "待初筛（旧）",
  contacted: "已联系（旧）",
  ongoing_follow: "人才储备（旧）",
  closed: "已结束（旧）",
};

function fmtTime(iso: string | null): string {
  if (!iso) return "";
  const raw = iso.includes("T") ? iso : iso.replace(" ", "T");
  const ms = new Date(raw.endsWith("Z") ? raw : raw + "Z").getTime();
  if (Number.isNaN(ms)) return iso.slice(0, 16).replace("T", " ");
  const d = new Date(ms);
  const sameDay = d.toDateString() === new Date().toDateString();
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return sameDay ? hm : `${d.getMonth() + 1}/${d.getDate()} ${hm}`;
}

/** HR 状态流转历史时间轴（默认折叠，点开懒加载；refreshKey 变化时重拉） */
export default function EngagementHistory({ candidateId, refreshKey }: Props) {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [loadedKey, setLoadedKey] = useState(-1);
  const { t } = useI18n();

  const load = useCallback(async (key: number) => {
    setLoading(true);
    try {
      setEntries((await api.candidates.engagementHistory(candidateId)) as HistoryEntry[]);
      setLoadedKey(key);
    } catch {
      setEntries([]);
      setLoadedKey(key);
    } finally {
      setLoading(false);
    }
  }, [candidateId]);

  // 展开时首次拉取；refreshKey 前进且已展开时重拉
  useEffect(() => {
    if (!open || loading) return;
    if (loadedKey < refreshKey) load(refreshKey);
  }, [open, refreshKey, loadedKey, loading, load]);

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-label text-on-surface-variant hover:text-on-surface cursor-pointer"
      >
        <Icon name={open ? "expand_less" : "expand_more"} size={16} />
        {t("流转历史")}
      </button>
      {open && (
        <div className="mt-2 pl-1">
          {loading ? (
            <LoadingIndicator size={16} strokeWidth={2} />
          ) : entries.length === 0 ? (
            <p className="text-label text-on-surface-variant">{t("暂无变更记录")}</p>
          ) : (
            <ol className="flex flex-col">
              {entries.map((e, i) => (
                <li key={i} className="relative pl-5 pb-2.5 last:pb-0">
                  {i < entries.length - 1 && (
                    <span className="absolute left-[5px] top-3 bottom-0 w-px bg-outline-variant" />
                  )}
                  <span
                    className={`absolute left-0 top-1.5 w-[11px] h-[11px] rounded-full border-2 border-surface ${
                      e.current_status === "rejected" || e.current_status === "departed"
                        ? "bg-error"
                        : e.current_status === "hired" || e.current_status === "offered"
                          ? "bg-success"
                          : "bg-primary"
                    }`}
                  />
                  <p className="text-body-sm text-on-surface">
                    {e.previous_status
                      ? `${t(STATUS_LABELS[e.previous_status] ?? e.previous_status)} → ${t(STATUS_LABELS[e.current_status] ?? e.current_status)}`
                      : t(STATUS_LABELS[e.current_status] ?? e.current_status)}
                    <span className="text-label text-on-surface-variant ml-2 font-mono">{fmtTime(e.changed_at)}</span>
                  </p>
                  <p className="text-label text-on-surface-variant">
                    {e.changed_by}
                    {e.note ? ` · ${e.note}` : ""}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}
