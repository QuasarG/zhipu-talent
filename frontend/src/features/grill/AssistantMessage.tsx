import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ThinkingOrb } from "thinking-orbs";
import type { GrillChatMessage as ChatMessage, GrillChatSegment as ChatSegment } from "@/lib/types";
import { StatusChip } from "@/components/ui/Chip";
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
    return (
      <ToolCallCard key={seg.call_id || i} segment={seg} interactive={interactive} onSend={onSend} userReply={userReply} />
    );
  };

  return (
    <div className="chat-enter flex gap-3">
      <div className="w-8 h-8 rounded-md bg-primary text-on-primary flex items-center justify-center text-body font-bold shrink-0 mt-0.5">
        AI
      </div>
      <div className="flex-1 min-w-0">
        {message.segments.map(renderSegment)}
        {busy && (
          <div className="mt-3 flex items-center gap-2">
            <ThinkingOrb state="shaping" size={20} aria-label="正在思考" />
            <span className="text-body-sm text-on-surface-variant">正在思考…</span>
          </div>
        )}
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
