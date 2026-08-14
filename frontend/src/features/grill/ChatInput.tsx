import { useRef, useState } from "react";
import { IconButton } from "@/components/ui/Button";
import Icon from "@/components/ui/Icon";
import { useI18n } from "@/lib/i18n";

interface Props {
  busy: boolean;
  onSend: (text: string) => void;
}

/** 对话输入条：Enter 发送，Shift+Enter 换行 */
export default function ChatInput({ busy, onSend }: Props) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  const { t } = useI18n();

  const send = () => {
    const text = value.trim();
    if (!text || busy) return;
    onSend(text);
    setValue("");
    if (ref.current) ref.current.style.height = "auto";
  };

  return (
    <div className="shrink-0">
      <div
        data-chat-input
        className="flex items-end gap-2 pl-4 pr-2 py-1.5 rounded-full bg-surface-lowest border border-outline-variant focus-within:outline-2 focus-within:outline-primary"
      >
        <Icon name="chat_bubble" size={18} className="text-on-surface-variant shrink-0 mb-2.5" />
        <textarea
          ref={ref}
          value={value}
          rows={1}
          disabled={busy}
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
          placeholder={t("回答 Agent 的问题，或描述你想招的人……")}
          className="flex-1 min-w-0 bg-transparent border-none outline-none resize-none py-2 text-body text-on-surface placeholder:text-on-surface-variant disabled:opacity-60"
        />
        <IconButton icon="send" variant="filled" onClick={send} disabled={busy || !value.trim()} />
      </div>
      <p className="text-center text-label text-on-surface-variant mt-2">
        {t("一次只问一个问题 · 说抽象词会被追问具体证据 · 前后矛盾会被当场指出")}
      </p>
    </div>
  );
}
