// 思考过程折叠卡：流式展开 + 用户可收起（问答/奖学金评分 agent 共用）
import { useEffect, useState } from "react";
import { ThinkingOrb } from "thinking-orbs";
import Icon from "@/components/ui/Icon";
import { useI18n } from "@/lib/i18n";

export default function ThinkingCard({ text, streaming }: { text: string; streaming: boolean }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(streaming);
  const [userToggled, setUserToggled] = useState(false);

  useEffect(() => {
    // 只跟随「开始流式」自动展开；流式结束不自动收起——
    // 评分 agent 每轮产生多个 thinking/text 交替段，自动收起会让折叠高度
    // 在流式期间反复变化，把整列布局顶得跳（闪烁）。收起交给用户手动。
    if (!userToggled && streaming && !open) setOpen(true);
  }, [streaming, userToggled, open]);

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
