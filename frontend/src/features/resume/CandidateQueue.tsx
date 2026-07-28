import { useState } from "react";
import type { CandidateBrief } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button from "@/components/ui/Button";
import SearchField from "@/components/ui/SearchField";
import SegmentedButtons from "@/components/ui/SegmentedButtons";
import { StatusChip } from "@/components/ui/Chip";
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
            return (
              <button
                key={c.id}
                onClick={() => onSelect(c.id)}
                className={cn(
                  "state-layer flex items-start gap-3 p-3 rounded-md text-left cursor-pointer transition-colors duration-150",
                  active ? "bg-secondary-container" : "bg-transparent"
                )}
              >
                {/* 头像色块：姓名首字 */}
                <span className="flex items-center justify-center w-9 h-9 rounded-sm bg-primary-container text-on-primary-container text-label shrink-0">
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
                </span>
              </button>
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
