import { useEffect, useRef, useState } from "react";
import type { CandidateDetail } from "@/lib/types";
import Icon from "@/components/ui/Icon";
import { StatusChip } from "@/components/ui/Chip";
import { cn } from "@/lib/cn";

interface Props {
  /** 当前候选人；null 时胶囊禁用、不显示下拉箭头 */
  candidate: CandidateDetail | null;
  /** 评估中状态，传 true 时禁用交互避免切换冲突 */
  busy?: boolean;
}

/**
 * 工具栏中央候选人胶囊：点击展开固定高度、内部可滚的元信息卡片。
 * - 未选候选人：胶囊禁用、不显示箭头
 * - 点外部 / ESC 关闭
 */
export default function CandidateMetaDropdown({ candidate, busy }: Props) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  // ESC 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // 点外部关闭
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    // 用 mousedown 避免和胶囊自身 click 冲突
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const disabled = !candidate || busy;
  const label = candidate ? `${candidate.name} · ${candidate.stage || "阶段未知"}` : "未选择候选人";

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "state-layer inline-flex items-center gap-2 h-9 px-4 rounded-full text-body-sm cursor-pointer select-none transition-colors",
          disabled
            ? "bg-surface-high text-on-surface-variant opacity-60 cursor-not-allowed"
            : "bg-surface-high text-on-surface hover:bg-surface-mid",
          open && !disabled && "ring-2 ring-primary"
        )}
      >
        <Icon name="person" size={16} className="text-on-surface-variant" />
        <span className="max-w-[280px] truncate">{label}</span>
        {candidate && !disabled && (
          <Icon
            name="expand_more"
            size={16}
            className={cn("text-on-surface-variant transition-transform duration-150", open && "rotate-180")}
          />
        )}
      </button>

      {open && candidate && (
        <div
          className="absolute left-1/2 -translate-x-1/2 top-full mt-2 w-[360px] rounded-lg border border-outline-variant bg-surface-lowest shadow-lg z-50 flex flex-col"
        >
          {/* 头部固定：姓名 + 关闭 */}
          <div className="shrink-0 flex items-center justify-between gap-2 px-4 py-3 border-b border-outline-variant">
            <div className="min-w-0">
              <p className="text-title text-on-surface truncate">{candidate.name}</p>
              <p className="text-label text-on-surface-variant truncate">{candidate.id}</p>
            </div>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="state-layer inline-flex items-center justify-center w-8 h-8 rounded-full text-on-surface-variant hover:text-on-surface cursor-pointer shrink-0"
              title="关闭"
            >
              <Icon name="close" size={18} />
            </button>
          </div>

          {/* 固定高度内容区，内部可滚 */}
          <div className="h-64 overflow-y-auto p-4">
            <dl className="grid grid-cols-[88px_minmax(0,1fr)] gap-x-3 gap-y-2.5">
              <MetaRow label="阶段" value={candidate.stage || "—"} />
              <MetaRow label="目标角色" value={candidate.role || "—"} />
              <MetaRow label="来源格式" value={sourceFormatLabel(candidate.source_format)} />
              <MetaRow label="导入分类" value={candidate.category || "—"} />
              <MetaRow label="导入级别" value={candidate.level || "—"} />
              <MetaRow label="HR 状态" value={hrStatusLabel(candidate.engagement_status)} />
              <MetaRow label="评估状态" value={candidate.evaluated ? "已评估" : "未评估"} />
              <MetaRow label="置信度" value={candidate.confidence != null ? `${(candidate.confidence * 100).toFixed(0)}%` : "—"} />
              {candidate.person_id && <MetaRow label="人才库 ID" value={candidate.person_id} mono />}
              {candidate.admitted_at && <MetaRow label="入库时间" value={candidate.admitted_at.slice(0, 16).replace("T", " ")} />}
            </dl>

            {candidate.directions?.length > 0 && (
              <div className="mt-4">
                <p className="text-label text-on-surface-variant mb-1.5">研究方向</p>
                <div className="flex flex-wrap gap-1.5">
                  {candidate.directions.map((d) => (
                    <StatusChip key={d} tone="info">{d}</StatusChip>
                  ))}
                </div>
              </div>
            )}

            {candidate.screening_tags?.length > 0 && (
              <div className="mt-4">
                <p className="text-label text-on-surface-variant mb-1.5">初筛标签</p>
                <div className="flex flex-wrap gap-1.5">
                  {candidate.screening_tags.map((t) => (
                    <StatusChip key={t} tone="neutral">{t}</StatusChip>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function MetaRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <>
      <dt className="text-body-sm text-on-surface-variant shrink-0 pt-0.5">{label}</dt>
      <dd className={cn("text-body-sm text-on-surface break-words", mono && "font-mono")}>{value}</dd>
    </>
  );
}

function sourceFormatLabel(fmt: string): string {
  switch (fmt) {
    case "pdf": return "PDF";
    case "text": return "文本";
    case "jsonl": return "JSONL";
    case "md": return "Markdown";
    default: return fmt || "—";
  }
}

function hrStatusLabel(status: string): string {
  const map: Record<string, string> = {
    newly_admitted: "新入库", to_contact: "待联系", contacted: "已联系",
    interviewing: "面试中", ongoing_follow: "持续关注", closed: "已结束",
  };
  return map[status] || status || "—";
}
