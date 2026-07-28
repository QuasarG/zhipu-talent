import { useState } from "react";
import type { CandidateBrief } from "@/lib/types";
import GlassPanel from "@/components/glass/GlassPanel";
import { Search, Upload } from "lucide-react";
import { cn } from "@/lib/cn";

interface Props {
  candidates: CandidateBrief[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onImport: () => void;
}

type Filter = "pending" | "completed" | "all";

function classifyCandidate(c: CandidateBrief): Filter {
  if (c.engagement_status && c.engagement_status !== "newly_admitted") return "completed";
  if (c.group === "pending") return "pending";
  return "completed";
}

export default function CandidateQueue({ candidates, selectedId, onSelect, onImport }: Props) {
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");

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
    <div className="flex flex-col gap-3 min-h-0">
      {/* 搜索 */}
      <GlassPanel className="flex items-center gap-2 px-3 py-2 rounded-[10px]">
        <Search size={16} className="text-ink-secondary shrink-0" />
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="搜索姓名、学校或方向"
          className="flex-1 border-none bg-transparent text-sm outline-none placeholder:text-ink-muted"
        />
      </GlassPanel>

      {/* segmented */}
      <div className="flex gap-1 p-1 rounded-[10px] bg-white/35">
        {(["all", "pending", "completed"] as Filter[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              "flex-1 flex items-center justify-center gap-1 px-2 py-1 rounded-full text-xs transition-colors",
              filter === f ? "bg-teal-soft text-teal" : "text-ink-secondary hover:text-ink"
            )}
          >
            {f === "all" ? "全部" : f === "pending" ? "待评估" : "已完成"}
            <span className="opacity-60">{counts[f]}</span>
          </button>
        ))}
      </div>

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto flex flex-col gap-0.5">
        {filtered.length === 0 ? (
          <div className="text-center py-10 text-sm text-ink-secondary">无匹配候选人</div>
        ) : (
          filtered.map((c) => (
            <button
              key={c.id}
              onClick={() => onSelect(c.id)}
              className={cn(
                "flex flex-col gap-0.5 p-3 rounded-[10px] text-left transition-colors border border-transparent",
                c.id === selectedId
                  ? "bg-teal-soft border-teal/20"
                  : "hover:bg-white/40"
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold">{c.name || c.id}</span>
                <span
                  className={cn(
                    "w-2 h-2 rounded-full shrink-0",
                    classifyCandidate(c) === "completed" ? "bg-teal-light" : "bg-ink-muted"
                  )}
                />
              </div>
              <div className="flex items-center gap-2 text-xs text-ink-secondary">
                <span className="flex-1 truncate">{c.role || c.stage || "—"}</span>
              </div>
            </button>
          ))
        )}
      </div>

      {/* 导入按钮 */}
      <button
        onClick={onImport}
        className="glass flex items-center justify-center gap-2 w-full py-3 rounded-[10px] text-sm font-medium text-teal hover:bg-white/70 transition-colors"
      >
        <Upload size={18} />
        <span>导入简历</span>
      </button>
    </div>
  );
}
