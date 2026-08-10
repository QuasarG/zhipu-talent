import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { ChatCitation } from "@/lib/types";
import { StatusChip } from "@/components/ui/Chip";
import Button from "@/components/ui/Button";
import Icon from "@/components/ui/Icon";

const statusTone = (status: string): { tone: "success" | "warning" | "error" | "neutral"; label: string } =>
  status === "confirmed"
    ? { tone: "success", label: "已确认" }
    : status === "conflict"
      ? { tone: "error", label: "冲突" }
      : status === "pending"
        ? { tone: "warning", label: "待核验" }
        : { tone: "neutral", label: status || "未知" };

const POPUP_WIDTH = 320; // w-80
const POPUP_MAX_H = 320;

type PersonMeta = NonNullable<ChatCitation["meta"]>;

function schoolText(s: unknown): string {
  if (typeof s === "string") return s;
  if (s && typeof s === "object") {
    const o = s as Record<string, unknown>;
    return [o.school, o.degree, o.period].filter(Boolean).map(String).join(" · ");
  }
  return "";
}

/** 人才库引用的详细档案卡：人物信息 + 跳转按钮 */
function PersonCard({ meta, close }: { meta: PersonMeta; close: () => void }) {
  const navigate = useNavigate();
  const schools = (meta.schools || []).map(schoolText).filter(Boolean);
  const go = (path: string) => {
    close();
    navigate(path);
  };
  return (
    <div>
      <div className="flex items-center gap-2">
        <p className="text-body font-bold text-on-surface break-words">{meta.name || "未命名"}</p>
        <StatusChip tone={meta.person_type === "guest" ? "warning" : "neutral"}>
          {meta.person_type === "guest" ? "嘉宾调查" : "简历人才"}
        </StatusChip>
        {meta.level && <StatusChip tone="success">{`评级 ${meta.level}`}</StatusChip>}
      </div>
      <div className="mt-2 flex flex-col gap-1 text-body-sm">
        <p className="text-on-surface-variant">
          <span className="text-on-surface">机构：</span>
          {meta.org || "—"}
        </p>
        <p className="text-on-surface-variant">
          <span className="text-on-surface">方向：</span>
          {meta.direction || "—"}
        </p>
        {meta.group && (
          <p className="text-on-surface-variant">
            <span className="text-on-surface">分组：</span>
            {meta.group}
          </p>
        )}
        {schools.length > 0 && (
          <p className="text-on-surface-variant">
            <span className="text-on-surface">教育：</span>
            {schools.join("；")}
          </p>
        )}
        {meta.overall_score != null && (
          <p className="text-on-surface-variant">
            <span className="text-on-surface">最新评估：</span>
            {meta.overall_score} 分{meta.tier ? ` · ${meta.tier}` : ""}
          </p>
        )}
      </div>
      <div className="flex justify-end gap-2 mt-3">
        <Button
          variant="outlined"
          icon="groups"
          className="h-8 px-3 text-xs"
          onClick={() => go(`/talent-pool?focus=${meta.person_id}`)}
        >
          人才库定位
        </Button>
        <Button
          variant="filled"
          icon="badge"
          className="h-8 px-3 text-xs"
          onClick={() => go(`/talent-pool/${meta.person_id}`)}
        >
          完整档案
        </Button>
      </div>
    </div>
  );
}

/** 正文引用角标 [^cN]：上标 badge，点击弹出来源卡片（fixed 定位，贴边自动翻转/夹取） */
export default function CitationBadge({ citation }: { citation: ChatCitation }) {
  const [open, setOpen] = useState(false);
  const [style, setStyle] = useState<React.CSSProperties>({});
  const btnRef = useRef<HTMLButtonElement>(null);
  const { tone, label } = statusTone(citation.status);
  const person = citation.meta?.person_id ? citation.meta : null;

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
            className="fixed z-50 w-80 overflow-y-auto p-3 rounded-md bg-surface-lowest border border-outline-variant shadow-1 text-left normal-case tracking-normal"
          >
            {person ? (
              <PersonCard meta={person} close={() => setOpen(false)} />
            ) : (
              <>
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
              </>
            )}
          </div>
        </>
      )}
    </sup>
  );
}
