import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ThinkingOrb } from "thinking-orbs";
import type { ChatCitation, ChatMessage, ChatSegment } from "@/lib/types";
import { StatusChip } from "@/components/ui/Chip";
import Icon from "@/components/ui/Icon";
import AgentWorkingBar from "@/components/ui/AgentWorkingBar";
import ToolCallCard from "./ToolCallCard";
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
    if (seg.type === "thinking") {
      return (
        <ThinkingCard
          key={`think-${i}`}
          text={seg.text}
          streaming={busy && message.status === "running" && i === message.content.segments.length - 1}
        />
      );
    }
    if (seg.type === "tool") return <ToolCallCard key={seg.call_id || i} segment={seg} />;
    return <ActionCard key={seg.action_id || i} segment={seg} busy={busy} onDecide={onDecide} />;
  };

  return (
    <div className="chat-enter flex gap-3">
      <div className="w-8 h-8 rounded-md bg-primary text-on-primary flex items-center justify-center text-body font-bold shrink-0 mt-0.5">
        Z
      </div>
      <div className="flex-1 min-w-0">
        {message.content.segments.map(renderSegment)}
        {busy && message.status !== "awaiting_action" && <AgentWorkingBar />}
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

/** 思考段与文本、工具卡按生成顺序持久展示；流式时展开，结束后收起。
 *  手动展开优先：一旦用户点开，后续 streaming 翻转不再劫持其状态。 */
function ThinkingCard({ text, streaming }: { text: string; streaming: boolean }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(streaming);
  const [userToggled, setUserToggled] = useState(false);

  useEffect(() => {
    if (!userToggled) setOpen(streaming);
  }, [streaming, userToggled]);

  const toggle = () => {
    setUserToggled(true);
    setOpen((value) => !value);
  };

  if (!text) return null;
  return (
    <div className="mb-3 rounded-md border border-outline-variant bg-surface-low overflow-hidden">
      <button
        type="button"
        onClick={toggle}
        className="state-layer flex items-center gap-2 w-full px-3 h-9 text-left cursor-pointer"
      >
        {streaming ? (
          <ThinkingOrb state="shaping" size={20} aria-label={t("正在思考")} />
        ) : (
          <Icon name="psychology" size={15} className="text-on-surface-variant" />
        )}
        <span className="text-label font-medium text-on-surface-variant truncate">
          {streaming ? t("思考中…") : t("思考过程")}
        </span>
        <Icon
          name={open ? "expand_less" : "expand_more"}
          size={16}
          className="ml-auto text-on-surface-variant"
        />
      </button>
      {open && (
        <pre className="px-3 pb-3 text-label leading-5 text-on-surface-variant whitespace-pre-wrap break-words max-h-56 overflow-y-auto select-text">
          {text}
        </pre>
      )}
    </div>
  );
}
