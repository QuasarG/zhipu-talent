import { useState, useEffect } from "react";
import type { PersonBrief } from "@/lib/types";
import { cn } from "@/lib/cn";
import Card from "@/components/ui/Card";
import { StatusChip } from "@/components/ui/Chip";
import { IconButton } from "@/components/ui/Button";
import Icon from "@/components/ui/Icon";
import { ENGAGEMENT_LABELS } from "./talentPoolModel";

interface Props {
  persons: PersonBrief[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onDelete?: (id: string) => void | Promise<void>;
}

export function classifyTrack(p: { direction?: string; dominant_track?: string; person_type?: string }): string {
  // 人物调查（guest）不参与 Track 分类
  if (p.person_type === "guest") return "";
  if (p.dominant_track) return p.dominant_track.toLowerCase();
  const d = (p.direction || "").toLowerCase();
  if (d.includes("agent")) return "agent";
  if (d.includes("safe")) return "safety";
  if (d.includes("system") || d.includes("infra")) return "ai_infra";
  if (d.includes("multimodal") || d.includes("多模态")) return "multimodal";
  if (d.includes("science") || d.includes("ai4s")) return "ai4science";
  return "";
}

export const STATUS_LABELS = ENGAGEMENT_LABELS;

export const TRACKS = ["base", "agent", "safety", "ai_infra", "multimodal", "ai4science"];

const HR_TONE: Record<string, "success" | "warning" | "info" | "primary" | "neutral"> = {
  newly_admitted: "neutral", screening: "warning", interviewing: "primary",
  offer_pending: "warning", offered: "info", hired: "success", departed: "neutral", rejected: "neutral",
};

const PAGE_SIZE = 10;

// 行网格：人才 | 状态 | 评分 | 时间
const ROW_GRID = "grid-cols-[minmax(0,1fr)_minmax(72px,auto)_minmax(40px,auto)_minmax(36px,auto)]";

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (d.toDateString() === new Date().toDateString()) return hm;
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function TalentList({ persons, selectedId, onSelect, onDelete }: Props) {
  const [page, setPage] = useState(1);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  useEffect(() => setPage(1), [persons]);

  const pageCount = Math.max(1, Math.ceil(persons.length / PAGE_SIZE));
  const current = Math.min(page, pageCount);
  const rows = persons.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);

  return (
    <Card variant="filled" className="w-full max-w-full flex flex-col min-h-0 min-w-0 overflow-hidden p-3">
      <div className="flex items-center justify-between px-1 pb-2 shrink-0">
        <span className="text-title">共 {persons.length} 位人才</span>
      </div>
      <div className={`grid ${ROW_GRID} gap-1.5 px-1 pb-1 text-label text-on-surface-variant shrink-0`}>
        <span>人才</span><span>状态</span><span className="text-right">更新</span>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden pb-2 flex flex-col gap-0.5">
        {rows.length === 0 ? (
          <div className="text-center py-8 text-body-sm text-on-surface-variant">无匹配人才</div>
        ) : (
          rows.map((p) => {
            const track = classifyTrack(p);
            const status = p.engagement_status || "newly_admitted";
            const active = p.id === selectedId;
            const confirming = confirmingId === p.id;
            const doDelete = async () => {
              if (!onDelete) return;
              setDeleting(true);
              try {
                await onDelete(p.id);
              } finally {
                setDeleting(false);
                setConfirmingId(null);
              }
            };
            return (
              <div
                key={p.id}
                role="button"
                tabIndex={0}
                onClick={() => !confirming && onSelect(p.id)}
                onKeyDown={(e) => {
                  if (!confirming && (e.key === "Enter" || e.key === " ")) {
                    e.preventDefault();
                    onSelect(p.id);
                  }
                }}
                className={cn(
                  "group relative grid gap-1.5 items-center px-2 py-2 rounded-md text-left cursor-pointer transition-colors outline-none",
                  ROW_GRID,
                  "focus-visible:ring-2 focus-visible:ring-primary",
                  confirming ? "bg-error-container" : active ? "bg-secondary-container" : "hover:bg-surface-low"
                )}
              >
                <span className="flex items-center gap-2 min-w-0">
                  <span className="w-9 h-9 rounded-full bg-primary-container text-on-primary-container flex items-center justify-center text-title shrink-0">
                    {(p.name || "?").charAt(0)}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-body font-medium text-on-surface truncate">{p.name || "未命名"}</span>
                    <span className="block text-body-sm text-on-surface-variant truncate capitalize">
                      {[
                        p.person_type === "guest" ? "人物调查" : "简历评估",
                        track,
                        p.org,
                      ].filter(Boolean).join(" · ") || "—"}
                    </span>
                  </span>
                </span>
                <StatusChip tone={HR_TONE[status] || "neutral"} className="min-w-0 justify-center whitespace-nowrap overflow-hidden text-ellipsis">
                  {STATUS_LABELS[status] || status}
                </StatusChip>
                {/* 评分列：仅简历评估类型显示 */}
                <span className="min-w-0 text-center">
                  {p.person_type !== "guest" && p.overall_score ? (
                    <span className="text-body-sm font-bold text-primary">{p.overall_score}</span>
                  ) : (
                    <span className="text-label text-on-surface-variant">—</span>
                  )}
                </span>
                <span className="min-w-0 text-label text-on-surface-variant truncate text-right">{fmtTime(p.updated_at)}</span>

                {/* hover 显示的删除按钮 */}
                {onDelete && !confirming && (
                  <span className="absolute top-0.5 right-0.5 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setConfirmingId(p.id); }}
                      className="state-layer inline-flex items-center justify-center w-7 h-7 rounded-full bg-surface-lowest text-on-surface-variant hover:text-error cursor-pointer shadow-sm"
                      title="删除"
                    >
                      <Icon name="delete" size={16} />
                    </button>
                  </span>
                )}

                {/* inline 二次确认条 */}
                {confirming && (
                  <span className="absolute inset-0 flex items-center justify-center gap-2 bg-error-container rounded-md">
                    <span className="text-body-sm font-semibold text-on-error-container">彻底删除此人的全部记录？</span>
                    <button
                      type="button"
                      disabled={deleting}
                      onClick={(e) => { e.stopPropagation(); doDelete(); }}
                      className="state-layer inline-flex items-center justify-center w-6 h-6 rounded-full bg-error text-on-error cursor-pointer disabled:opacity-40"
                      title="确认删除"
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
                )}
              </div>
            );
          })
        )}
      </div>

      <div className="flex items-center justify-center gap-1 px-4 py-2 border-t border-outline-variant shrink-0">
        <IconButton icon="chevron_left" size={18} className="w-8 h-8" disabled={current <= 1} onClick={() => setPage(current - 1)} />
        {Array.from({ length: pageCount }, (_, i) => i + 1).slice(0, 5).map((n) => (
          <button
            key={n}
            onClick={() => setPage(n)}
            className={cn(
              "state-layer w-8 h-8 rounded-full text-label cursor-pointer",
              n === current ? "bg-primary text-on-primary" : "text-on-surface-variant"
            )}
          >
            {n}
          </button>
        ))}
        <IconButton icon="chevron_right" size={18} className="w-8 h-8" disabled={current >= pageCount} onClick={() => setPage(current + 1)} />
        <span className="ml-2 text-label text-on-surface-variant">{PAGE_SIZE} 条/页</span>
      </div>
    </Card>
  );
}
