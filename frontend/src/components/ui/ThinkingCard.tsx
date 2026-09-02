// 思考过程折叠卡：流式展开 + 用户可收起（问答/奖学金评分 agent 共用）
// memo：流式时已完成思考段 text/streaming 恒定，不随每 token 重渲染（防闪烁）
import { memo, useEffect, useState } from "react";
import { ThinkingOrb } from "thinking-orbs";
import Icon from "@/components/ui/Icon";
import { useI18n } from "@/lib/i18n";

export default memo(function ThinkingCard({ text, streaming }: { text: string; streaming: boolean }) {
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
});
