import { useState, useEffect } from "react";
import type { PersonBrief } from "@/lib/types";
import { cn } from "@/lib/cn";
import Card from "@/components/ui/Card";
import { StatusChip } from "@/components/ui/Chip";
import { IconButton } from "@/components/ui/Button";

interface Props {
  persons: PersonBrief[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function classifyTrack(p: { direction?: string }): string {
  const d = (p.direction || "").toLowerCase();
  if (d.includes("agent")) return "agent";
  if (d.includes("safe")) return "safety";
  if (d.includes("system")) return "systems";
  if (d.includes("multimodal") || d.includes("多模态")) return "multimodal";
  if (d.includes("science") || d.includes("ai4s")) return "ai4science";
  return "";
}

export const STATUS_LABELS: Record<string, string> = {
  newly_admitted: "新入库", to_contact: "待联系", contacted: "已联系",
  interviewing: "面试中", ongoing_follow: "持续关注", closed: "已结束",
};

export const TRACKS = ["agent", "safety", "systems", "multimodal", "ai4science"];

const HR_TONE: Record<string, "success" | "warning" | "info" | "primary" | "neutral"> = {
  newly_admitted: "neutral", to_contact: "warning", contacted: "info",
  interviewing: "primary", ongoing_follow: "success", closed: "neutral",
};

const PAGE_SIZE = 10;

function fmtTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (d.toDateString() === new Date().toDateString()) return hm;
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function TalentList({ persons, selectedId, onSelect }: Props) {
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [persons]);

  const pageCount = Math.max(1, Math.ceil(persons.length / PAGE_SIZE));
  const current = Math.min(page, pageCount);
  const rows = persons.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);

  return (
    <Card variant="elevated" className="flex flex-col min-h-0">
      <div className="flex items-center justify-between px-4 pt-3 pb-2 shrink-0">
        <span className="text-title">共 {persons.length} 位人才</span>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_56px_62px_58px_36px] gap-1.5 px-2 pb-1 text-label text-on-surface-variant shrink-0">
        <span>人才</span><span>Track</span><span>来源</span><span>状态</span><span>更新</span>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-2 flex flex-col gap-0.5">
        {rows.length === 0 ? (
          <div className="text-center py-8 text-body-sm text-on-surface-variant">无匹配人才</div>
        ) : (
          rows.map((p) => {
            const track = classifyTrack(p);
            const status = p.engagement_status || "newly_admitted";
            const active = p.id === selectedId;
            return (
              <button
                key={p.id}
                onClick={() => onSelect(p.id)}
                className={cn(
                  "state-layer grid grid-cols-[minmax(0,1fr)_56px_62px_58px_36px] gap-1.5 items-center px-2 py-2 rounded-md text-left cursor-pointer transition-colors",
                  active ? "bg-secondary-container" : "hover:bg-surface-low"
                )}
              >
                <span className="flex items-center gap-2 min-w-0">
                  <span className="w-9 h-9 rounded-full bg-primary-container text-on-primary-container flex items-center justify-center text-title shrink-0">
                    {(p.name || "?").charAt(0)}
                  </span>
                  <span className="min-w-0">
                    <span className="block text-body font-medium text-on-surface truncate">{p.name || p.id}</span>
                    <span className="block text-body-sm text-on-surface-variant truncate">{p.org || "—"}</span>
                  </span>
                </span>
                <span className="text-body-sm text-on-surface-variant capitalize truncate">{track || "—"}</span>
                <StatusChip tone={p.person_type === "guest" ? "info" : "primary"}>
                  {p.person_type === "guest" ? "人物调查" : "简历评估"}
                </StatusChip>
                <StatusChip tone={HR_TONE[status] || "neutral"}>
                  {STATUS_LABELS[status] || status}
                </StatusChip>
                <span className="text-label text-on-surface-variant">{fmtTime(p.updated_at)}</span>
              </button>
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
