import { useRef, useState } from "react";
import { IconButton } from "@/components/ui/Button";
import Icon from "@/components/ui/Icon";

interface Props {
  busy: boolean;
  awaitingAction: boolean;
  onSend: (text: string) => void;
}

/** 对话输入条：Enter 发送，Shift+Enter 换行 */
export default function ChatInput({ busy, awaitingAction, onSend }: Props) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  const disabled = busy || awaitingAction;

  const send = () => {
    const text = value.trim();
    if (!text || disabled) return;
    onSend(text);
    setValue("");
    if (ref.current) ref.current.style.height = "auto";
  };

  return (
    <div className="shrink-0">
      <div data-chat-input className="flex items-end gap-2 pl-4 pr-2 py-1.5 rounded-full bg-surface-lowest border border-outline-variant focus-within:outline-2 focus-within:outline-primary">
        <Icon name="chat_bubble" size={18} className="text-on-surface-variant shrink-0 mb-2.5" />
        <textarea
          ref={ref}
          value={value}
          rows={1}
          disabled={disabled}
          onChange={(e) => {
            setValue(e.target.value);
            e.target.style.height = "auto";
            e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          placeholder={
            awaitingAction ? "请先完成上方选择" : "询问人才、比较经历，或调查一个明确人物……"
          }
          className="flex-1 min-w-0 bg-transparent border-none outline-none resize-none py-2 text-body text-on-surface placeholder:text-on-surface-variant disabled:opacity-60"
        />
        <IconButton icon="send" variant="filled" onClick={send} disabled={disabled || !value.trim()} />
      </div>
      <p className="text-center text-label text-on-surface-variant mt-2">
        {awaitingAction ? "完成上方卡片的决策后，Agent 将继续回答" : "库内优先 · 必要时联网调查；新事实将以待核验状态保存"}
      </p>
    </div>
  );
}
