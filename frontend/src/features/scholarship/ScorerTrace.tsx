// 评分 agent 工作记录：对话流样式渲染 trace segments（复用问答的 ToolCallCard 动效）
import { useState } from "react";
import { ThinkingOrb } from "thinking-orbs";
import type { ScorerTraceSegment } from "@/lib/types";
import Icon from "@/components/ui/Icon";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/cn";

const TOOL_ICONS: Record<string, string> = {
  list_files: "folder_open",
  read_file: "description",
  verify_paper: "travel_explore",
  web_search: "search",
  submit_scores: "grade",
};

/** 单条轨迹卡片：完成态折叠成一行，运行中 shaping orb */
function TraceToolCard({ segment }: { segment: Extract<ScorerTraceSegment, { type: "tool" }> }) {
  const [expanded, setExpanded] = useState(false);
  const { t } = useI18n();
  const failed = segment.status === "error";

  let pretty = segment.detail;
  try {
    pretty = JSON.stringify(JSON.parse(segment.detail), null, 2);
  } catch {
    /* 非 JSON 原样展示 */
  }

  return (
    <div
      className={cn(
        "chat-enter my-2 rounded-md border text-body-sm overflow-hidden",
        failed ? "border-error/40 bg-error-container/30" : "border-outline-variant bg-surface-low"
      )}
    >
      <button
        type="button"
        onClick={() => segment.detail && setExpanded((v) => !v)}
        className={cn("w-full flex items-center gap-2 px-3 py-2 text-left", segment.detail ? "cursor-pointer" : "cursor-default")}
      >
        <Icon name={TOOL_ICONS[segment.tool] ?? "build"} size={18} className="text-primary shrink-0" />
        <span className="font-medium text-on-surface shrink-0">{segment.label || segment.tool}</span>
        <span className="flex-1 min-w-0 truncate text-on-surface-variant">{segment.summary}</span>
        {segment.detail && <Icon name={expanded ? "expand_less" : "expand_more"} size={18} className="text-on-surface-variant shrink-0" />}
      </button>
      {expanded && segment.detail && (
        <pre className="px-3 pb-2.5 max-h-64 overflow-auto font-mono text-xs text-on-surface-variant whitespace-pre-wrap break-all">
          {pretty}
        </pre>
      )}
    </div>
  );
}

/** 运行中占位：正在思考的 orb（对话 agent 同款动效） */
function RunningOrb({ label }: { label: string }) {
  return (
    <div className="chat-enter my-2 flex items-center gap-2.5 rounded-md border border-outline-variant bg-surface-low px-3 py-2 text-body-sm text-on-surface-variant">
      <ThinkingOrb state="shaping" size={20} aria-label={label} />
      <span>{label}</span>
    </div>
  );
}

interface Props {
  trace: ScorerTraceSegment[];
  running: boolean;
}

/** agent 工作记录（无用户输入的对话流）：读完 trace，running 时尾部挂 orb */
export default function ScorerTrace({ trace, running }: Props) {
  const { t } = useI18n();
  if (!trace.length && !running) {
    return (
      <div className="rounded-lg border border-dashed border-outline-variant px-4 py-8 text-body-sm text-on-surface-variant">
        {t("暂无评估过程记录，点上方「开始评估」生成")}
      </div>
    );
  }
  return (
    <div className="flex flex-col">
      {trace.map((segment, i) => {
        if (segment.type === "tool") return <TraceToolCard key={`${segment.call_id}-${i}`} segment={segment} />;
        if (segment.type === "final")
          return (
            <div key={i} className="chat-enter my-2 flex items-center gap-2 rounded-md border border-primary/40 bg-primary-container/40 px-3 py-2.5 text-body-sm text-on-surface">
              <Icon name="verified" size={18} className="text-primary shrink-0" />
              <span className="font-medium">{segment.text}</span>
            </div>
          );
        return (
          <p key={i} className="chat-enter my-2 px-1 text-body-sm text-on-surface-variant">
            {segment.text}
          </p>
        );
      })}
      {running && <RunningOrb label={t("评审 agent 工作中…")} />}
    </div>
  );
}
