import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ThinkingOrb } from "thinking-orbs";
import type { GrillChatMessage as ChatMessage, GrillChatSegment as ChatSegment } from "@/lib/types";
import { StatusChip } from "@/components/ui/Chip";
import Icon from "@/components/ui/Icon";
import AgentWorkingBar from "@/components/ui/AgentWorkingBar";
import { useI18n } from "@/lib/i18n";
import ToolCallCard from "./ToolCallCard";

interface Props {
  message: ChatMessage;
  busy: boolean;
  /** 仅最新消息且空闲时 true：提问卡选项可点 */
  interactive?: boolean;
  onSend?: (text: string) => void;
  /** 紧随其后的用户消息原文：历史回放时据此回显卡片已选项 */
  userReply?: string;
}

/** assistant 消息：按 segments 顺序渲染 文本(markdown) / 工具卡片 */
export default function AssistantMessage({ message, busy, interactive = false, onSend, userReply }: Props) {
  const renderSegment = (seg: ChatSegment, i: number) => {
    if (seg.type === "text") {
      if (!seg.text.trim()) return null;
      return (
        <div key={i} className="chat-markdown text-on-surface">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{seg.text}</ReactMarkdown>
        </div>
      );
    }
    if (seg.type === "thinking") {
      return (
        <ThinkingCard
          key={`think-${i}`}
          text={seg.text}
          streaming={busy && i === message.segments.length - 1}
        />
      );
    }
    return <ToolCallCard key={seg.call_id || i} segment={seg} interactive={interactive} onSend={onSend} userReply={userReply} />;
  };

  return (
    <div className="chat-enter flex gap-3">
      <div className="w-8 h-8 rounded-md bg-primary text-on-primary flex items-center justify-center text-body font-bold shrink-0 mt-0.5">
        AI
      </div>
      <div className="flex-1 min-w-0">
        {message.segments.map(renderSegment)}
        {busy && <AgentWorkingBar />}
        {message.error && (
          <div className="mt-2">
            <StatusChip tone="error" variant="filled" icon="error">
              {message.error}
            </StatusChip>
          </div>
        )}
      </div>
    </div>
  );
}

function ThinkingCard({ text, streaming }: { text: string; streaming: boolean }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(streaming);

  useEffect(() => {
    setOpen(streaming);
  }, [streaming]);

  if (!text) return null;
  return (
    <div className="mb-3 rounded-md border border-outline-variant bg-surface-low overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
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
        <Icon name={open ? "expand_less" : "expand_more"} size={16} className="ml-auto text-on-surface-variant" />
      </button>
      {open && (
        <pre className="px-3 pb-3 text-label leading-5 text-on-surface-variant whitespace-pre-wrap break-words max-h-56 overflow-y-auto select-text">
          {text}
        </pre>
      )}
    </div>
  );
}
