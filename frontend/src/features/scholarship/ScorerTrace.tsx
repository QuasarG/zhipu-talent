// 评分 agent 工作记录：对话流样式，组件层直接复用问答的 ThinkingCard / ToolCallCard
import { useState } from "react";
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

/** trace tool segment → ChatSegment.tool 适配（直接喂问答的 ToolCallCard） */
function toChatToolSeg(seg: Extract<ScorerTraceSegment, { type: "tool" }>): Extract<ChatSegment, { type: "tool" }> {
  return {
    type: "tool",
    call_id: seg.call_id,
    tool: seg.tool,
    label: seg.label || TOOL_LABELS[seg.tool] || seg.tool,
    status: seg.status === "error" ? "error" : "ok",
    summary: seg.summary,
    detail: seg.detail,
    args_summary: "",
  };
}

interface Props {
  /** 进行中的实时流（问答原生 ChatSegment 形状，来自 applyEvent） */
  live?: ChatSegment[];
  /** 落库的回放轨迹（含 final 段） */
  trace: ScorerTraceSegment[];
  running: boolean;
}

/** agent 工作记录（无用户输入的对话流） */
export default function ScorerTrace({ live, trace, running }: Props) {
  const { t } = useI18n();
  const [filter, setFilter] = useState<"all" | "thinking">("all");
  // 实时流优先（进行中）；结束后切到落库 trace（含 final 横幅）
  const active: ScorerTraceSegment[] =
    live && live.length
      ? live.map((s) =>
          s.type === "tool"
            ? { type: "tool", call_id: s.call_id, tool: s.tool, label: s.label, status: s.status ?? "", summary: s.summary ?? "", detail: s.detail ?? "" }
            : s.type === "text"
              ? { type: "text", text: s.text }
              : { type: "thinking", text: s.text }
        )
      : trace;
  const lastThinking = running ? active.length - 1 : -1;
  if (!active.length && !running) {
    return (
      <div className="rounded-lg border border-dashed border-outline-variant px-4 py-8 text-body-sm text-on-surface-variant">
        {t("暂无评估过程记录，点上方「开始评估」生成")}
      </div>
    );
  }
  const hasThinking = active.some((s) => s.type === "thinking");
  const shown = filter === "all" ? active : active.filter((s) => s.type === "thinking");
  return (
    <div className="flex flex-col">
      {hasThinking && (
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
      {shown.map((segment, i) => {
        if (segment.type === "thinking")
          return (
            <ThinkingCard
              key={`think-${i}`}
              text={segment.text}
              streaming={running && i === lastThinking}
            />
          );
        if (segment.type === "tool")
          return <ToolCallCard key={`${segment.call_id}-${i}`} segment={toChatToolSeg(segment)} />;
        if (segment.type === "final")
          return (
            <div key={i} className="chat-enter my-2 flex flex-wrap items-center gap-2 rounded-md border border-primary/40 bg-primary-container/40 px-3 py-2.5 text-body-sm text-on-surface">
              <Icon name="verified" size={18} className="text-primary shrink-0" />
              <span className="font-medium">{segment.text}</span>
              {segment.reputation_findings?.length ? (
                <StatusChip tone="warning">{t("{n} 条舆情发现", { n: segment.reputation_findings.length })}</StatusChip>
              ) : null}
            </div>
          );
        // content 段：与问答正文同款 markdown 渲染（chat-markdown 字体/排版），不用卡片
        return (
          <div key={i} className="chat-enter chat-markdown text-on-surface my-2">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{segment.text}</ReactMarkdown>
          </div>
        );
      })}
    </div>
  );
}
