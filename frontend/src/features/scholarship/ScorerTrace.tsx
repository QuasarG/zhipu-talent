// 评分 agent 工作记录：结构与问答 AssistantMessage 完全一致——
// segments 按顺序渲染 thinking 卡 / 工具卡 / markdown 正文，无中间归一化层。
// 防闪烁的关键（从问答照搬）：
// 1. live 段对象身份跨事件稳定（applyEvent 只替换尾部），memo 按 seg 身份生效；
// 2. streaming = 最后一个段（问答同款判定），思考结束即收起，视口由外层自动滚底钉住。
import { memo, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatSegment, ScorerTraceSegment } from "@/lib/types";
import Icon from "@/components/ui/Icon";
import ThinkingCard from "@/components/ui/ThinkingCard";
import ToolCallCard from "@/features/chat/ToolCallCard";
import { StatusChip } from "@/components/ui/Chip";
import { useI18n } from "@/lib/i18n";

const TOOL_LABELS: Record<string, string> = {
  list_files: "盘点材料",
  read_file: "读取材料",
  verify_paper: "论文查证",
  web_search: "全网检索",
  submit_scores: "提交评分",
};

/** 落库 trace（回放）→ ChatSegment 形状；只在 trace 变化时算一次，不在流式路径上 */
function traceToChatSegments(trace: ScorerTraceSegment[]): ChatSegment[] {
  const out: ChatSegment[] = [];
  for (const seg of trace) {
    if (seg.type === "tool")
      out.push({
        type: "tool",
        call_id: seg.call_id,
        tool: seg.tool,
        label: seg.label || TOOL_LABELS[seg.tool] || seg.tool,
        status: seg.status === "error" ? "error" : "ok",
        summary: seg.summary,
        detail: seg.detail,
        args_summary: "",
      });
    else if (seg.type === "thinking") out.push({ type: "thinking", text: seg.text });
    else if (seg.type === "text") out.push({ type: "text", text: seg.text });
    // final 段单独渲染，不进 ChatSegment 流
  }
  return out;
}

// ---- 段组件：memo 按 props 身份短路（live 路径段对象身份稳定，前面的卡完全不重渲染） ----

const ThinkingItem = memo(function ThinkingItem({ text, streaming }: { text: string; streaming: boolean }) {
  return <ThinkingCard text={text} streaming={streaming} />;
});

const ToolItem = memo(function ToolItem({ seg }: { seg: Extract<ChatSegment, { type: "tool" }> }) {
  return <ToolCallCard segment={seg} />;
});

const TextItem = memo(function TextItem({ text }: { text: string }) {
  return (
    <div className="chat-markdown text-on-surface my-2">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
});

interface Props {
  /** 进行中的实时流（applyEvent 产物，段身份稳定）；优先使用 */
  live?: ChatSegment[];
  /** 落库的回放轨迹（结束后切换，含 final 横幅） */
  trace: ScorerTraceSegment[];
  running: boolean;
}

/** agent 工作记录（无用户输入的对话流） */
export default function ScorerTrace({ live, trace, running }: Props) {
  const { t } = useI18n();
  const [filter, setFilter] = useState<"all" | "thinking">("all");
  const finalSeg = useMemo(
    () => trace.find((s) => s.type === "final") as Extract<ScorerTraceSegment, { type: "final" }> | undefined,
    [trace],
  );
  // live 优先（流式中，段身份稳定）；否则回放 trace 转换（一次性 useMemo）
  const segments = useMemo(
    () => (live && live.length ? live : traceToChatSegments(trace)),
    [live, trace],
  );
  if (!segments.length && !running && !finalSeg) {
    return (
      <div className="rounded-lg border border-dashed border-outline-variant px-4 py-8 text-body-sm text-on-surface-variant">
        {t("暂无评估过程记录，点上方「开始评估」生成")}
      </div>
    );
  }
  const shown = filter === "all" ? segments : segments.filter((s) => s.type === "thinking");
  const lastIdx = segments.length - 1; // streaming 判定与问答一致：最后一个段
  return (
    <div className="flex flex-col">
      {segments.some((s) => s.type === "thinking") && (
        <div className="mb-2 flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setFilter("all")}
            className={`state-layer h-7 rounded-full px-3 text-label cursor-pointer ${filter === "all" ? "bg-primary text-on-primary" : "text-on-surface-variant"}`}
          >
            {t("全部记录")}
          </button>
          <button
            type="button"
            onClick={() => setFilter("thinking")}
            className={`state-layer h-7 rounded-full px-3 text-label cursor-pointer ${filter === "thinking" ? "bg-primary text-on-primary" : "text-on-surface-variant"}`}
          >
            {t("仅思考")}
          </button>
        </div>
      )}
      {shown.map((seg, i, arr) => {
        const orderOf = (type: string) => arr.slice(0, i).filter((s) => s.type === type).length;
        if (seg.type === "thinking")
          return <ThinkingItem key={`think-${orderOf("thinking")}`} text={seg.text} streaming={running && i === lastIdx} />;
        if (seg.type === "tool") return <ToolItem key={`tool-${seg.call_id}`} seg={seg} />;
        if (!seg.text.trim()) return null;
        return <TextItem key={`text-${orderOf("text")}`} text={seg.text} />;
      })}
      {finalSeg && (
        <div className="chat-enter my-2 flex flex-wrap items-center gap-2 rounded-md border border-primary/40 bg-primary-container/40 px-3 py-2.5 text-body-sm text-on-surface">
          <Icon name="verified" size={18} className="text-primary shrink-0" />
          <span className="font-medium">{finalSeg.text}</span>
          {finalSeg.reputation_findings?.length ? (
            <StatusChip tone="warning">{t("{n} 条舆情发现", { n: finalSeg.reputation_findings.length })}</StatusChip>
          ) : null}
        </div>
      )}
    </div>
  );
}
