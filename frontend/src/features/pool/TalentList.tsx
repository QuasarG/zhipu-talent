import type { PersonBrief } from "@/lib/types";
import { cn } from "@/lib/cn";

interface Props {
  persons: PersonBrief[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  trackFilter: string;
  setTrackFilter: (v: string) => void;
}

function classifyTrack(p: PersonBrief): string {
  const d = (p.direction || "").toLowerCase();
  if (d.includes("agent")) return "agent";
  if (d.includes("safe")) return "safety";
  if (d.includes("system")) return "systems";
  if (d.includes("multimodal") || d.includes("多模态")) return "multimodal";
  if (d.includes("science") || d.includes("ai4s")) return "ai4science";
  return "";
}

const STATUS_LABELS: Record<string, string> = {
  newly_admitted: "新入库", to_contact: "待联系", contacted: "已联系",
  interviewing: "面试中", ongoing_follow: "持续关注", closed: "已结束",
};

const TRACKS = ["agent", "safety", "systems", "multimodal", "ai4science"];

export default function TalentList({ persons, selectedId, onSelect, trackFilter, setTrackFilter }: Props) {
  const filtered = trackFilter ? persons.filter((p) => classifyTrack(p) === trackFilter) : persons;

  return (
    <div className="flex flex-col gap-2 min-h-0">
      <div className="flex flex-wrap gap-1 shrink-0">
        <button
          onClick={() => setTrackFilter("")}
          className={cn("text-[10px] px-2.5 py-1 rounded-full transition-colors", !trackFilter ? "bg-teal-soft text-teal" : "bg-white/35 text-ink-secondary")}
        >
          全部
        </button>
        {TRACKS.map((t) => (
          <button
            key={t}
            onClick={() => setTrackFilter(t)}
            className={cn("text-[10px] px-2.5 py-1 rounded-full capitalize transition-colors", trackFilter === t ? "bg-teal-soft text-teal" : "bg-white/35 text-ink-secondary")}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto flex flex-col gap-0.5">
        {filtered.length === 0 ? (
          <div className="text-center py-8 text-sm text-ink-secondary">无匹配人才</div>
        ) : (
          filtered.map((p) => (
            <button
              key={p.id}
              onClick={() => onSelect(p.id)}
              className={cn(
                "flex flex-col gap-0.5 p-3 rounded-[10px] text-left border border-transparent transition-colors",
                p.id === selectedId ? "bg-teal-soft border-teal/20" : "hover:bg-white/40"
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold">{p.name || p.id}</span>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-surface-mist text-ink-secondary">
                  {STATUS_LABELS[p.engagement_status || "newly_admitted"] || p.engagement_status}
                </span>
              </div>
              <div className="text-xs text-ink-secondary truncate">
                {p.org || "—"} · {classifyTrack(p) || "未分类"}
              </div>
              <div className="flex gap-1 mt-0.5">
                <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full", p.person_type === "guest" ? "bg-blue-soft text-blue" : "bg-teal-soft text-teal")}>
                  {p.person_type === "guest" ? "人物调查" : "简历评估"}
                </span>
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
