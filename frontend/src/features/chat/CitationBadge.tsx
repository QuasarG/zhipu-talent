import { useRef, useState } from "react";
import type { ChatCitation } from "@/lib/types";
import { StatusChip } from "@/components/ui/Chip";
import Icon from "@/components/ui/Icon";

const statusTone = (status: string): { tone: "success" | "warning" | "error" | "neutral"; label: string } =>
  status === "confirmed"
    ? { tone: "success", label: "已确认" }
    : status === "conflict"
      ? { tone: "error", label: "冲突" }
      : status === "pending"
        ? { tone: "warning", label: "待核验" }
        : { tone: "neutral", label: status || "未知" };

const POPUP_WIDTH = 288; // w-72
const POPUP_MAX_H = 256;

/** 正文引用角标 [^cN]：上标 badge，点击弹出来源卡片（fixed 定位，贴边自动翻转/夹取） */
export default function CitationBadge({ citation }: { citation: ChatCitation }) {
  const [open, setOpen] = useState(false);
  const [style, setStyle] = useState<React.CSSProperties>({});
  const btnRef = useRef<HTMLButtonElement>(null);
  const { tone, label } = statusTone(citation.status);

  const toggle = () => {
    if (!open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect();
      const left = Math.min(Math.max(8, r.left), window.innerWidth - POPUP_WIDTH - 8);
      // 下方空间不够就向上弹，避免被滚动容器截断
      const flipUp = window.innerHeight - r.bottom < POPUP_MAX_H + 16 && r.top > POPUP_MAX_H + 16;
      setStyle(
        flipUp
          ? { left, bottom: window.innerHeight - r.top + 6, maxHeight: POPUP_MAX_H }
          : { left, top: r.bottom + 6, maxHeight: POPUP_MAX_H }
      );
    }
    setOpen((v) => !v);
  };

  return (
    <sup className="inline-block">
      <button
        ref={btnRef}
        type="button"
        onClick={toggle}
        className="state-layer ml-0.5 px-1 rounded-xs bg-primary-container text-on-primary-container text-[10px] font-semibold cursor-pointer leading-4"
      >
        {citation.id}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div
            style={style}
            className="fixed z-50 w-72 overflow-y-auto p-3 rounded-md bg-surface-lowest border border-outline-variant shadow-1 text-left normal-case tracking-normal"
          >
            <p className="text-body-sm font-medium text-on-surface break-words">{citation.title || citation.id}</p>
            <div className="flex items-center gap-2 mt-1.5">
              <span className="text-label text-on-surface-variant">{citation.type || "来源"}</span>
              <StatusChip tone={tone}>{label}</StatusChip>
            </div>
            {citation.url && (
              <a
                href={citation.url}
                target="_blank"
                rel="noreferrer"
                className="mt-1.5 inline-flex items-center gap-1 text-label text-primary hover:underline break-all"
              >
                <Icon name="open_in_new" size={14} />
                {citation.url}
              </a>
            )}
          </div>
        </>
      )}
    </sup>
  );
}
