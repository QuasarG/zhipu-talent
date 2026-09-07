import { useEffect, useRef, useState } from "react";
import Icon from "@/components/ui/Icon";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";
import { activeAgents, roleNames, type Activity } from "./agentActivityModel";

const kinds: Record<string, string> = { dispatch: "派工", handoff: "回传 / 交接", request: "开始工作",
  message: "工作说明", tool_call: "调用工具", tool_result: "工具返回", error: "执行失败", status: "进度", legacy: "历史记录" };

export default function AgentWorkbench({ events, status, mode }: {
  events: Activity[]; status: string; mode: "panel" | "admission";
}) {
  const { t } = useI18n();
  const [filter, setFilter] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const scroll = useRef<HTMLDivElement>(null);
  const running = status === "running";
  const active = activeAgents(events, running);
  const roster = new Map<string, Activity>();
  events.forEach(e => { if (e.role !== "system") roster.set(e.agent, e); });
  const visible = filter ? events.filter(e => e.agent === filter || e.target === filter) : events;
  const nameOf = (id: string) => t(roleNames[roster.get(id)?.role || id] || id);
  useEffect(() => {
    if (follow && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
  }, [events.length, follow, filter]);
  const statusLabel = status === "completed" ? "已完成" : status === "failed" ? "运行失败"
    : status === "cancelled" ? "已停止" : running ? "运行中" : "排队中";

  return (
    <section className="flex h-full min-h-[400px] min-w-0 flex-col bg-surface-lowest" aria-label={t("Agent 协作工作台")}>
      <header className="shrink-0 border-b border-outline-variant px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-title-lg font-semibold">{t("Agent 协作")}</h2>
          <span className="flex items-center gap-2 text-label text-on-surface-variant">
            <span className={cn("h-2 w-2 rounded-full", running ? "bg-primary motion-safe:animate-pulse" : status === "failed" ? "bg-error" : "bg-outline")} />
            {t(statusLabel)}
          </span>
        </div>
        <p className="mt-1 text-label text-on-surface-variant">{t(mode === "panel"
          ? "主席派工 · 评审员逐个执行 · 结论回传 · 系统裁决"
          : "能力映射 · 多任务并行评分 · 独立总审 · 系统裁决")}</p>
        {mode === "panel" && events.length >= 400 && <p className="mt-1 text-label text-on-surface-variant">{t("仅保留最近 400 条记录，早期活动可能已截断")}</p>}
        <div className="mt-4 max-h-48 space-y-2 overflow-y-auto" aria-live="polite">
          {active.length ? active.map(e => (
            <div key={e.agent} className="flex items-start gap-3">
              <Icon name="activity" size={18} className="mt-0.5 shrink-0 text-primary" />
              <div className="min-w-0">
                <p className="text-body-sm font-semibold">{t(roleNames[e.role] || e.role)}
                  {e.mission && <span className="ml-2 text-label font-normal text-on-surface-variant">{e.mission}</span>}
                </p>
                <p className="mt-0.5 break-words text-body-sm text-on-surface-variant">{e.text}</p>
              </div>
            </div>
          )) : <p className="text-body-sm text-on-surface-variant">{t(running
            ? "等待下一条执行事件；暂未收到正在工作的实例信息"
            : status === "queued" ? "等待评估启动" : "本次运行已结束，可查看以下协作记录")}</p>}
        </div>
      </header>
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-outline-variant px-5 py-2">
            <span className="text-label text-on-surface-variant">{filter ? nameOf(filter) : t("全部协作记录")} · {visible.length}</span>
            <button type="button" aria-pressed={follow} onClick={() => setFollow(!follow)} className="rounded px-2 py-1 text-label hover:bg-surface-low focus-visible:outline-2 focus-visible:outline-primary">
              {t(follow ? "暂停跟随" : "跟随最新")}
            </button>
          </div>
          <div ref={scroll} className="min-h-0 flex-1 overflow-y-auto px-5 admission-panel-scrollbar">
            {!visible.length && <p className="py-12 text-center text-body-sm text-on-surface-variant">{t("尚未收到协作记录")}</p>}
            {visible.map(e => (
              <article key={e.id} className="border-b border-outline-variant py-4 last:border-0">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-label">
                  <span className="font-semibold">{t(roleNames[e.role] || e.role)}</span>
                  {e.mission && <span className="text-on-surface-variant">{e.mission}</span>}
                  {e.target && <><Icon name="arrow-right" size={13} /><span>{nameOf(e.target)}</span>
                    {e.target !== "chair" && e.target !== "system" && <span className="text-on-surface-variant">{e.target}</span>}</>}
                  <span className="text-on-surface-variant">· {t(kinds[e.kind] || e.kind)}</span>
                  {e.at && <time className="ml-auto tabular-nums text-on-surface-variant">{new Date(e.at).toLocaleTimeString()}</time>}
                </div>
                <p className={cn("mt-2 whitespace-pre-wrap break-words text-body-sm leading-relaxed", e.status === "failed" ? "text-error" : "text-on-surface")}>{e.text}</p>
                {e.kind === "legacy" && <p className="mt-1 text-label text-on-surface-variant">{t("历史记录未保存收发对象，不推断交接关系")}</p>}
                {e.detail && Object.keys(e.detail).length > 0 && <details className="mt-2">
                  <summary className="cursor-pointer rounded py-1 text-label font-medium text-primary focus-visible:outline-2 focus-visible:outline-primary">{t("查看输入、输出与依据")}</summary>
                  <div className="mt-2 space-y-3 border-t border-outline-variant py-3">
                    {Object.entries(e.detail).map(([key, value]) => <div key={key}>
                      <p className="text-label font-semibold">{key}</p>
                      <pre className="mt-1 max-h-80 overflow-auto whitespace-pre-wrap break-words font-sans text-body-sm leading-relaxed text-on-surface-variant">{typeof value === "string" ? value : JSON.stringify(value, null, 2)}</pre>
                    </div>)}
                  </div>
                </details>}
              </article>
            ))}
          </div>
        </div>
        <aside className="max-h-44 shrink-0 overflow-y-auto border-t border-outline-variant bg-surface-low/40 p-3 lg:max-h-none lg:w-56 lg:border-t-0 lg:border-l">
          <p className="px-2 py-2 text-label font-semibold">{t("本次 Agent 实例")} · {roster.size}</p>
          <button type="button" onClick={() => setFilter(null)} aria-pressed={!filter} className={cn("mb-1 w-full rounded-md px-2 py-2 text-left text-label focus-visible:outline-2 focus-visible:outline-primary", !filter && "bg-secondary-container")}>{t("全部记录")}</button>
          {[...roster].map(([id, e]) => <button key={id} type="button" onClick={() => setFilter(id)} aria-pressed={filter === id}
            className={cn("mb-1 w-full rounded-md px-2 py-2 text-left hover:bg-surface-low focus-visible:outline-2 focus-visible:outline-primary", filter === id && "bg-secondary-container")}>
            <span className="block text-body-sm font-medium">{t(roleNames[e.role] || e.role)} {e.mission || ""}</span>
            {e.goal && <span className="mt-1 block break-words text-label text-on-surface-variant">{e.goal}</span>}
            <span className="mt-1 block text-label text-on-surface-variant">{t(active.some(a => a.agent === id) ? "正在工作" : e.status === "failed" ? "失败" : e.kind === "handoff" ? "已回传" : "最近活动已记录")}</span>
          </button>)}
        </aside>
      </div>
    </section>
  );
}
