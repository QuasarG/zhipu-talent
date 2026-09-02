// 评分 agent 工作记录：对话流样式，组件层直接复用问答的 ThinkingCard / ToolCallCard。
// 防闪烁三原则：
// 1. 稳定 key（同类段次序 / call_id），追加不漂移；
// 2. 段级 memo：列表项按 props 内容记忆化，尾部流式追加只重渲染最后一项；
// 3. chat-enter 只给「一次性出现」的元素（工具卡/终态横幅），流式正文不带。
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

// ---- 段级 memo 组件：props 不变就不重渲染（流式追加时前面的卡纹丝不动） ----

const ThinkingItem = memo(function ThinkingItem({ text, streaming }: { text: string; streaming: boolean }) {
  return <ThinkingCard text={text} streaming={streaming} />;
});

const ToolItem = memo(function ToolItem({ seg, animate }: { seg: Extract<ScorerTraceSegment, { type: "tool" }>; animate: boolean }) {
  return <ToolCallCard segment={toChatToolSeg(seg)} animate={animate} />;
});

const TextItem = memo(function TextItem({ text }: { text: string }) {
  // content 段：与问答正文同款 markdown 渲染（chat-markdown 字体/排版），不用卡片
  return (
    <div className="chat-markdown text-on-surface my-2">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
});

const FinalItem = memo(function FinalItem({ text, findings }: { text: string; findings: number }) {
  const { t } = useI18n();
  return (
    <div className="chat-enter my-2 flex flex-wrap items-center gap-2 rounded-md border border-primary/40 bg-primary-container/40 px-3 py-2.5 text-body-sm text-on-surface">
      <Icon name="verified" size={18} className="text-primary shrink-0" />
      <span className="font-medium">{text}</span>
      {findings > 0 ? <StatusChip tone="warning">{t("{n} 条舆情发现", { n: findings })}</StatusChip> : null}
    </div>
  );
});

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
  // 归一化：live（问答 ChatSegment）→ 本组件的 ScorerTraceSegment 形状
  const active: ScorerTraceSegment[] = useMemo(
    () =>
      live && live.length
        ? live.map((s) =>
            s.type === "tool"
              ? { type: "tool", call_id: s.call_id, tool: s.tool, label: s.label, status: s.status ?? "", summary: s.summary ?? "", detail: s.detail ?? "" }
              : s.type === "text"
                ? { type: "text", text: s.text }
                : { type: "thinking", text: s.text }
          )
        : trace,
    [live, trace],
  );
  const hasThinking = active.some((s) => s.type === "thinking");
  const shown = useMemo(
    () => (filter === "all" ? active : active.filter((s) => s.type === "thinking")),
    [active, filter],
  );
  // streaming 标记：running 时最后一个 thinking 段在思考。
  // 曾用 active.length-1：reasoning/content 交替追加导致折叠卡反复收起/展开（闪烁根因之一）。
  const lastThinkingIndex = running
    ? shown.reduce((last, s, idx) => (s.type === "thinking" ? idx : last), -1)
    : -1;
  if (!active.length && !running) {
    return (
      <div className="rounded-lg border border-dashed border-outline-variant px-4 py-8 text-body-sm text-on-surface-variant">
        {t("暂无评估过程记录，点上方「开始评估」生成")}
      </div>
    );
  }
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
      {shown.map((segment, i, arr) => {
        // 稳定 key：同类段内的次序（段创建时即确定，后续追加不漂移）
        const orderOf = (type: string) => arr.slice(0, i).filter((s) => s.type === type).length;
        if (segment.type === "thinking")
          return (
            <ThinkingItem
              key={`think-${orderOf("thinking")}`}
              text={segment.text}
              streaming={i === lastThinkingIndex}
            />
          );
        if (segment.type === "tool") return <ToolItem key={`tool-${segment.call_id}`} seg={segment} animate={!running} />;
        if (segment.type === "final")
          return <FinalItem key="final" text={segment.text} findings={segment.reputation_findings?.length ?? 0} />;
        return <TextItem key={`text-${orderOf("text")}`} text={segment.text} />;
      })}
    </div>
  );
}
