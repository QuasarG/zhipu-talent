import { useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ThinkingOrb } from "thinking-orbs";
import type { ChatCitation, ChatMessage, ChatSegment } from "@/lib/types";
import { StatusChip } from "@/components/ui/Chip";
import ActionCard from "./ActionCard";
import CitationBadge from "./CitationBadge";
import { useI18n } from "@/lib/i18n";

interface Props {
  message: ChatMessage;
  error?: string;
  busy: boolean;
  onDecide: (actionId: string, decision: Record<string, unknown>) => void;
}

interface MdNode {
  type: string;
  value?: string;
  url?: string;
  children?: MdNode[];
}

const CITE_RE = /\[\^(c\d+)\]/g;

/** 把已注册引用的 [^cN] 转成 #cite-cN 链接节点；未注册的原样保留（防模型幻觉角标） */
function citePlugin(citations: ChatCitation[]) {
  const ids = new Set(citations.map((c) => c.id));
  const transform = (node: MdNode) => {
    if (!node.children) return;
    if (node.type === "code" || node.type === "inlineCode") return;
    const next: MdNode[] = [];
    for (const child of node.children) {
      if (child.type === "text" && child.value && CITE_RE.test(child.value)) {
        CITE_RE.lastIndex = 0;
        let last = 0;
        let match: RegExpExecArray | null;
        while ((match = CITE_RE.exec(child.value))) {
          if (!ids.has(match[1])) continue;
          if (match.index > last) {
            next.push({ type: "text", value: child.value.slice(last, match.index) });
          }
          next.push({
            type: "link",
            url: `#cite-${match[1]}`,
            children: [{ type: "text", value: match[0] }],
          });
          last = match.index + match[0].length;
        }
        if (last === 0) {
          next.push(child);
        } else {
          if (last < child.value.length) next.push({ type: "text", value: child.value.slice(last) });
          continue;
        }
      } else {
        transform(child);
        next.push(child);
      }
    }
    node.children = next;
  };
  return () => (tree: MdNode) => transform(tree);
}

/** assistant 消息：按 segments 顺序渲染 文本(markdown) / 工具卡片 / 决策卡片 */
export default function AssistantMessage({ message, error, busy, onDecide }: Props) {
  const { t } = useI18n();
  const citationMap = useMemo(
    () => new Map((message.citations || []).map((c) => [c.id, c])),
    [message.citations]
  );
  const plugins = useMemo(
    () => [remarkGfm, citePlugin(message.citations || [])],
    [message.citations]
  );

  const renderSegment = (seg: ChatSegment, i: number) => {
    if (seg.type === "text") {
      if (!seg.text.trim()) return null;
      return (
        <div key={i} className="chat-markdown text-on-surface">
          <ReactMarkdown
            remarkPlugins={plugins}
            components={{
              a: ({ href, children }) => {
                const id = href?.startsWith("#cite-") ? href.slice(6) : "";
                const citation = id ? citationMap.get(id) : undefined;
                if (citation) return <CitationBadge citation={citation} />;
                return (
                  <a href={href} target="_blank" rel="noreferrer">
                    {children}
                  </a>
                );
              },
            }}
          >
            {seg.text}
          </ReactMarkdown>
        </div>
      );
    }
    if (seg.type === "thinking") return null;
    if (seg.type === "tool") return null;
    return <ActionCard key={seg.action_id || i} segment={seg} busy={busy} onDecide={onDecide} />;
  };

  return (
    <div className="chat-enter flex gap-3">
      <div className="w-8 h-8 rounded-md bg-primary text-on-primary flex items-center justify-center text-body font-bold shrink-0 mt-0.5">
        Z
      </div>
      <div className="flex-1 min-w-0">
        {busy && <CurrentRoundTrace segments={message.content.segments} />}
        {message.content.segments.map(renderSegment)}
        {busy && message.status !== "awaiting_action" && !message.content.segments.length && (
          <div className="mt-3 flex items-center gap-2">
            <ThinkingOrb state="shaping" size={20} aria-label={t("正在思考")} />
            <span className="text-body-sm text-on-surface-variant">{t("正在思考…")}</span>
          </div>
        )}
        {error && (
          <div className="mt-2">
            <StatusChip tone="error" variant="filled" icon="error">
              {error}
            </StatusChip>
          </div>
        )}
      </div>
    </div>
  );
}

function CurrentRoundTrace({ segments }: { segments: ChatSegment[] }) {
  const tools = segments.filter((segment): segment is Extract<ChatSegment, { type: "tool" }> => segment.type === "tool");
  const hasAnswer = segments.some((segment) => segment.type === "text" && segment.text.trim());
  const hasThinking = segments.some((segment) => segment.type === "thinking");
  return <div className="mb-3 rounded-md border border-outline-variant bg-surface-low p-3">
    <div className="relative pl-6 flex flex-col gap-2 before:absolute before:left-[5px] before:top-2 before:bottom-2 before:w-px before:bg-outline-variant">
      <TraceStep label="理解问题" active={hasThinking && !tools.length && !hasAnswer} done={tools.length > 0 || hasAnswer} />
      {tools.map((tool) => <TraceStep key={tool.call_id} label={tool.label || tool.tool} active={!tool.status} done={!!tool.status} failed={tool.status === "error"} summary={tool.summary || tool.args_summary} />)}
      {hasAnswer && <TraceStep label="组织回答" active done={false} />}
    </div>
  </div>;
}

function TraceStep({ label, active, done, failed = false, summary }: { label: string; active: boolean; done: boolean; failed?: boolean; summary?: string }) {
  return <div className="relative min-h-7">
    <span className={`absolute -left-6 top-1.5 w-2.5 h-2.5 rounded-full ring-4 ring-surface-low ${failed ? "bg-error" : done ? "bg-success" : "bg-primary"}`} />
    <div className="flex items-center gap-2"><span className="text-label font-medium">{label}</span>{active && <ThinkingOrb state="shaping" size={20} aria-label="运行中" />}</div>
    {summary && <p className="text-label text-on-surface-variant truncate">{summary}</p>}
  </div>;
}
