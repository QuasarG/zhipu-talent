import { memo, useState } from "react";
import type { ChatSegment } from "@/lib/types";
import Icon from "@/components/ui/Icon";
import { ThinkingOrb } from "thinking-orbs";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

type ToolSegment = Extract<ChatSegment, { type: "tool" }>;

/** detail 是 JSON 字符串就格式化，否则原样展示 */
function prettyDetail(detail: string): string {
  try {
    return JSON.stringify(JSON.parse(detail), null, 2);
  } catch {
    return detail;
  }
}

/** 工具调用卡片：运行中 = shaping orb 轨迹形变动效；完成后折叠成一行摘要。
 *  memo：流式时段对象引用稳定，已完成卡片不随每 token 重渲染（防闪烁）。 */
export default memo(function ToolCallCard({ segment }: { segment: ToolSegment }) {
  const [expanded, setExpanded] = useState(false);
  const { t } = useI18n();
  const running = !segment.status;
  const failed = segment.status === "error";

  return (
    <div
      className={cn(
        "chat-enter my-2 rounded-md border text-body-sm overflow-hidden",
        failed ? "border-error/40 bg-error-container/30" : "border-outline-variant bg-surface-low"
      )}
    >
      <button
        type="button"
        onClick={() => !running && segment.detail && setExpanded((v) => !v)}
        className={cn(
          "w-full flex items-center gap-2 px-3 py-2 text-left",
          !running && segment.detail ? "cursor-pointer" : "cursor-default"
        )}
      >
        {running ? (
          <ThinkingOrb state="shaping" size={20} className="shrink-0" aria-label={t("正在调用工具")} />
        ) : failed ? (
          <Icon name="error" size={18} fill className="text-error shrink-0" />
        ) : (
          <Icon name="check_circle" size={18} fill className="text-success shrink-0" />
        )}
        <span className="font-medium text-on-surface shrink-0">{segment.label || segment.tool}</span>
        <span className="flex-1 min-w-0 truncate text-on-surface-variant">
          {running ? segment.args_summary : failed ? t("失败 · {summary}", { summary: String(segment.summary) }) : segment.summary}
        </span>
        {!running && segment.detail && (
          <Icon
            name={expanded ? "expand_less" : "expand_more"}
            size={18}
            className="text-on-surface-variant shrink-0"
          />
        )}
      </button>
      {expanded && segment.detail && (
        <pre className="px-3 pb-2.5 max-h-64 overflow-auto font-mono text-xs text-on-surface-variant whitespace-pre-wrap break-all">
          {prettyDetail(segment.detail)}
        </pre>
      )}
    </div>
  );
});
