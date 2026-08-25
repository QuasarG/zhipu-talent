import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ThinkingOrb } from "thinking-orbs";
import type { GrillChatMessage as ChatMessage, GrillChatSegment as ChatSegment } from "@/lib/types";
import { StatusChip } from "@/components/ui/Chip";
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
  const { t } = useI18n();
  const renderSegment = (seg: ChatSegment, i: number) => {
    if (seg.type === "text") {
      if (!seg.text.trim()) return null;
      return (
        <div key={i} className="chat-markdown text-on-surface">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{seg.text}</ReactMarkdown>
        </div>
      );
    }
    if (seg.tool !== "ask_question" && seg.tool !== "search_jobs") return null;
    return <ToolCallCard key={seg.call_id || i} segment={seg} interactive={interactive} onSend={onSend} userReply={userReply} />;
  };

  return (
    <div className="chat-enter flex gap-3">
      <div className="w-8 h-8 rounded-md bg-primary text-on-primary flex items-center justify-center text-body font-bold shrink-0 mt-0.5">
        AI
      </div>
      <div className="flex-1 min-w-0">
        {busy && <CurrentRoundTrace segments={message.segments} />}
        {message.segments.map(renderSegment)}
        {busy && !message.segments.length && (
          <div className="mt-3 flex items-center gap-2">
            <ThinkingOrb state="shaping" size={20} aria-label={t("正在思考")} />
            <span className="text-body-sm text-on-surface-variant">{t("正在思考…")}</span>
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


function CurrentRoundTrace({ segments }: { segments: ChatSegment[] }) {
  const tools = segments.filter((segment): segment is Extract<ChatSegment, { type: "tool" }> => segment.type === "tool");
  const hasText = segments.some((segment) => segment.type === "text" && segment.text.trim());
  return <div className="mb-3 rounded-md border border-outline-variant bg-surface-low p-3">
    <div className="relative pl-6 flex flex-col gap-2 before:absolute before:left-[5px] before:top-2 before:bottom-2 before:w-px before:bg-outline-variant">
      <TraceStep label="理解当前回答" active={!tools.length && !hasText} done={tools.length > 0 || hasText} />
      {tools.map((tool) => <TraceStep key={tool.call_id} label={tool.label || tool.tool} active={!tool.status} done={!!tool.status} failed={tool.status === "error"} summary={tool.summary || tool.args_summary} />)}
      {hasText && <TraceStep label="更新画像并组织追问" active done={false} />}
    </div>
  </div>;
}

function TraceStep({ label, active, done, failed = false, summary }: { label: string; active: boolean; done: boolean; failed?: boolean; summary?: string }) {
  return <div className="relative min-h-7"><span className={`absolute -left-6 top-1.5 w-2.5 h-2.5 rounded-full ring-4 ring-surface-low ${failed ? "bg-error" : done ? "bg-success" : "bg-primary"}`} /><div className="flex items-center gap-2"><span className="text-label font-medium">{label}</span>{active && <ThinkingOrb state="shaping" size={20} aria-label="运行中" />}</div>{summary && <p className="text-label text-on-surface-variant truncate">{summary}</p>}</div>;
}
