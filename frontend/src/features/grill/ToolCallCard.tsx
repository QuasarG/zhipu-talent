import { useState } from "react";
import { ThinkingOrb } from "thinking-orbs";
import type { GrillToolSegment as ToolSegment } from "@/lib/types";
import Button, { IconButton } from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import { StatusChip } from "@/components/ui/Chip";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/cn";

/** detail 是 JSON 字符串就格式化，否则原样展示 */
function prettyDetail(detail: string): string {
  try {
    return JSON.stringify(JSON.parse(detail), null, 2);
  } catch {
    return detail;
  }
}

interface AskGroup {
  text: string;
  options: string[];
  multi_select?: boolean;
}

// 兜底项模式：LLM 生成的这类选项一律过滤，兜底由前端统一追加
const FALLBACK_RE = /我直接说|其他|以上都不是|补充说明/;

/** 解析 ask_question 的 detail：归一化为子问题组（单问 = 长度 1）；LLM 给的兜底项滤掉，由前端统一追加 */
function parseAskGroups(detail?: string): AskGroup[] {
  if (!detail) return [];
  try {
    const d = JSON.parse(detail);
    const clean = (v: unknown): string[] =>
      Array.isArray(v)
        ? v.filter((o): o is string => typeof o === "string" && !!o.trim() && !FALLBACK_RE.test(o))
        : [];
    if (Array.isArray(d.questions) && d.questions.length) {
      return d.questions
        .filter((q: unknown) => q && typeof (q as AskGroup).text === "string")
        .map((q: AskGroup) => ({ text: q.text, options: clean(q.options), multi_select: !!q.multi_select }));
    }
    return d.question
      ? [{ text: String(d.question), options: clean(d.options), multi_select: !!d.multi_select }]
      : [];
  } catch {
    return [];
  }
}

// 选项回答统一带此前缀：后端历史与 prompt 据此区分「用户选的」与「用户说的」
const OPTION_MARK = "【选择了预设选项】";
// 每组末尾前端追加的自填项（不依赖 LLM 生成）
const OTHER = "其他（自己填）";

/**
 * 历史回显：从「选择了预设选项」回复反推每组选中的选项文本。
 * 只认精确匹配（手打/截断的文本自动降级为不高亮，不瞎标）。
 */
function parseAskReply(reply: string | undefined, groups: AskGroup[]): Record<number, string[]> {
  const out: Record<number, string[]> = {};
  if (!reply || !reply.startsWith(OPTION_MARK) || !groups.length) return out;
  const body = reply.slice(OPTION_MARK.length).trim();
  if (!body) return out;
  if (groups.length === 1) {
    // 单问：单选直达是整段文本；多选用「；」连接（也可能混入「、」）
    const opts = groups[0].options;
    const candidates = [body, ...body.split(/[；;、]/)].map((s) => s.trim());
    const hits = candidates.filter((c) => opts.includes(c));
    if (hits.length) out[0] = [...new Set(hits)];
    return out;
  }
  // 合并卡：每段形如「N. 问题文本：答案1、答案2」，编号按已答组重排过，故按问题文本定位分组
  for (const part of body.split(/[；;]/)) {
    const seg = part.trim().replace(/^\d+\s*[.、]?\s*/, "");
    groups.forEach((g, gi) => {
      if (!seg.startsWith(`${g.text}：`)) return;
      const hits = seg
        .slice(g.text.length + 1)
        .split(/[、,，]/)
        .map((s) => s.trim())
        .filter((s) => g.options.includes(s));
      if (hits.length) out[gi] = [...new Set([...(out[gi] || []), ...hits])];
    });
  }
  return out;
}

/** 历史回显：岗位卡提交回复「我觉得「X」和我的需求最契合（岗位ID: …）」→ 命中岗位下标 / 全不符合 */
function parseJobReply(reply: string | undefined, jobs: JobItem[]): { idx: number | null; noneFit: boolean } {
  const none = { idx: null, noneFit: false };
  if (!reply || !reply.startsWith(OPTION_MARK) || !jobs.length) return none;
  const body = reply.slice(OPTION_MARK.length);
  if (body.includes("以上岗位都不太符合")) return { idx: null, noneFit: true };
  const byTitle = body.match(/我觉得「(.+?)」和我的需求最契合/);
  if (byTitle) {
    const i = jobs.findIndex((j) => j.title === byTitle[1]);
    if (i >= 0) return { idx: i, noneFit: false };
  }
  const byId = body.match(/岗位ID:\s*([^）)\s]+)/);
  if (byId) {
    const i = jobs.findIndex((j) => j.job_id === byId[1]);
    if (i >= 0) return { idx: i, noneFit: false };
  }
  return none;
}

interface AskCardProps {
  segment: ToolSegment;
  interactive: boolean;
  onSend?: (text: string) => void;
  /** 紧随其后的用户消息原文：历史回放时据此回显已选项 */
  userReply?: string;
}

/** 提问卡：单问单选 = 点选项即答；多选组可叠加；多子问题 = 各组选完底部合并提交 */
function AskQuestionCard({ segment, interactive, onSend, userReply }: AskCardProps) {
  const { t } = useI18n();
  const running = !segment.status;
  const groups = running ? [] : parseAskGroups(segment.detail);
  const merged = groups.length > 1;
  const [picked, setPicked] = useState<Record<number, string[]>>({});
  const [custom, setCustom] = useState<Record<number, string>>({});
  // 历史回放：从下一条用户消息反推当时选中的选项（精确匹配不上就不高亮）
  const historyPicked = interactive ? {} : parseAskReply(userReply, groups);

  // 组回答数组：普通项取文案；「其他」取自填文本（未填不计）；多选组可多项
  const answersOf = (gi: number): string[] =>
    (picked[gi] || []).flatMap((p) =>
      p === OTHER ? (custom[gi]?.trim() ? [custom[gi].trim()] : []) : [p]
    );
  const answeredCount = groups.filter((_, gi) => answersOf(gi).length > 0).length;

  const toggle = (gi: number, opt: string) =>
    setPicked((prev) => {
      const cur = prev[gi] || [];
      const next = cur.includes(opt)
        ? cur.filter((o) => o !== opt) // 再点取消，自填文本保留
        : groups[gi]?.multi_select
          ? [...cur, opt]
          : [opt]; // 单选组互斥替换
      return { ...prev, [gi]: next };
    });

  const submitMerged = () => {
    const text = groups
      .map((g, gi) => {
        const a = answersOf(gi);
        return a.length ? `${g.text}：${a.join("、")}` : null;
      })
      .filter(Boolean)
      .map((line, i) => `${i + 1}. ${line}`)
      .join("；");
    onSend?.(`${OPTION_MARK}${text}`);
  };

  const optionBtn = (gi: number, opt: string) => {
    const on = (picked[gi] || []).includes(opt);
    const historyOn = !on && (historyPicked[gi] || []).includes(opt);
    return (
      <button
        key={opt}
        type="button"
        disabled={!interactive}
        onClick={() => {
          if (!interactive) return;
          if (!merged && !groups[0]?.multi_select && !on) {
            onSend?.(`${OPTION_MARK}${opt}`); // 单问单选：点选项直接发
            return;
          }
          toggle(gi, opt);
        }}
        className={cn(
          "state-layer rounded-full border px-3 py-1.5 text-left text-body-sm",
          on
            ? "border-primary bg-primary text-on-primary"
            : historyOn
              ? "border-primary bg-primary text-on-primary opacity-70 cursor-default" // 历史回显：选中但禁用
              : interactive
                ? "border-primary/50 bg-surface-lowest text-primary cursor-pointer"
                : "border-outline-variant text-on-surface-variant/70 cursor-default"
        )}
      >
        {opt}
      </button>
    );
  };

  /** 「其他（自己填）」：未选中是普通 chip；选中后 pill 原地变输入框，不再另开第二个框 */
  const otherPill = (gi: number) => {
    const on = (picked[gi] || []).includes(OTHER);
    if (!on) {
      return (
        <button
          key={OTHER}
          type="button"
          disabled={!interactive}
          onClick={() => interactive && toggle(gi, OTHER)}
          className={cn(
            "state-layer rounded-full border px-3 py-1.5 text-left text-body-sm",
            interactive
              ? "border-primary/50 bg-surface-lowest text-primary cursor-pointer"
              : "border-outline-variant text-on-surface-variant/70 cursor-default"
          )}
        >
          {t(OTHER)}
        </button>
      );
    }
    return (
      <div
        key={OTHER}
        className="flex items-center rounded-full border border-primary bg-primary px-3 py-1.5 text-body-sm"
      >
        <input
          autoFocus
          value={custom[gi] || ""}
          disabled={!interactive}
          onChange={(e) => setCustom((prev) => ({ ...prev, [gi]: e.target.value }))}
          onBlur={() => {
            if (!custom[gi]?.trim()) toggle(gi, OTHER); // 清空失焦 = 退回普通 chip
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setCustom((prev) => ({ ...prev, [gi]: "" }));
              toggle(gi, OTHER);
            } else if (e.key === "Enter") {
              const t = custom[gi]?.trim();
              if (!t) return;
              if (merged || groups[gi]?.multi_select) e.currentTarget.blur(); // 合并卡/多选：Enter 只确认该组
              else onSend?.(`${OPTION_MARK}${t}`); // 单问单选：Enter 等同发送
            }
          }}
          placeholder={t("输入你的回答…")}
          className="w-full min-w-0 bg-transparent text-on-primary placeholder:text-on-primary/60 outline-none disabled:opacity-60"
        />
      </div>
    );
  };

  const multiChip = (
    <StatusChip tone="primary" className="h-5 px-2 align-middle">
      {t("多选")}
    </StatusChip>
  );

  return (
    <div className="chat-enter my-2 rounded-lg border border-primary/30 bg-primary-container/40 px-4 py-3">
      <div className="flex items-center gap-1.5 text-label text-primary">
        {running ? (
          <ThinkingOrb state="shaping" size={20} aria-label={t("正在构思问题")} />
        ) : (
          <Icon name="quiz" size={16} />
        )}
        <span>{t(segment.label) || t("提问")}</span>
      </div>

      {running ? (
        <p className="mt-1 text-body text-on-surface">{t("正在构思问题…")}</p>
      ) : merged ? (
        <div className="mt-1 space-y-3">
          {groups.map((g, gi) => (
            <div key={gi}>
              <p className="text-body text-on-surface whitespace-pre-wrap">
                {gi + 1}. {g.text} {g.multi_select && multiChip}
              </p>
              <div className="mt-1 flex flex-col gap-1.5">
                {g.options.map((opt) => optionBtn(gi, opt))}
                {g.options.length > 0 && otherPill(gi)}
              </div>
            </div>
          ))}
          <div className="flex items-center gap-2">
            <Button
              variant="filled"
              icon="send"
              className="h-8 px-4"
              disabled={!interactive || answeredCount === 0}
              onClick={submitMerged}
            >
              {t("提交回答（{answered}/{total}）", { answered: answeredCount, total: groups.length })}
            </Button>
            <span className="text-label text-on-surface-variant">{t("可留空，也可以直接在下方输入框回答")}</span>
          </div>
        </div>
      ) : (
        <>
          <p className="mt-1 text-body text-on-surface whitespace-pre-wrap">
            {groups[0]?.text || segment.summary} {groups[0]?.multi_select && multiChip}
          </p>
          {!!groups[0]?.options.length && (
            <div className="mt-2 flex flex-col gap-1.5">
              {groups[0].options.map((opt) => optionBtn(0, opt))}
              {otherPill(0)}
            </div>
          )}
          {groups[0]?.multi_select && (
            <Button
              variant="filled"
              icon="send"
              className="mt-2 h-8 px-4"
              disabled={!interactive || answersOf(0).length === 0}
              onClick={() => onSend?.(`${OPTION_MARK}${answersOf(0).join("；")}`)}
            >
              {t("提交回答")}{answersOf(0).length > 0 ? t("（已选 {n} 项）", { n: answersOf(0).length }) : ""}
            </Button>
          )}
        </>
      )}
    </div>
  );
}

interface JobItem {
  job_id?: string;
  title?: string;
  job_category?: string;
  city_info?: string;
  recruit_type?: string;
  requirement_excerpt?: string;
  description?: string;
  requirement?: string;
  score?: number;
}

function parseJobs(detail?: string): JobItem[] {
  if (!detail) return [];
  try {
    const d = JSON.parse(detail);
    return Array.isArray(d.jobs) ? d.jobs.filter((j: JobItem) => j && j.title) : [];
  } catch {
    return [];
  }
}

/** 岗位详情弹窗：完整 description/requirement，可滚动 */
function JobDetailDialog({ job, onClose }: { job: JobItem; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-inverse-surface/40 p-6"
      onClick={onClose}
    >
      <Card
        variant="elevated"
        className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-xl p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-title-lg">{job.title}</h3>
          <IconButton icon="close" onClick={onClose} />
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {job.job_category && <StatusChip tone="neutral">{job.job_category}</StatusChip>}
          {job.city_info && <StatusChip tone="neutral">{job.city_info}</StatusChip>}
          {job.recruit_type && <StatusChip tone="info">{job.recruit_type}</StatusChip>}
          {typeof job.score === "number" && (
            <StatusChip tone="primary">{t("契合 {pct}%", { pct: Math.round(job.score * 100) })}</StatusChip>
          )}
        </div>
        {job.description && (
          <section className="mt-3">
            <p className="mb-1 text-label text-on-surface-variant">{t("岗位描述")}</p>
            <p className="whitespace-pre-wrap text-body-sm text-on-surface">{job.description}</p>
          </section>
        )}
        {job.requirement && (
          <section className="mt-3">
            <p className="mb-1 text-label text-on-surface-variant">{t("岗位要求")}</p>
            <p className="whitespace-pre-wrap text-body-sm text-on-surface">{job.requirement}</p>
          </section>
        )}
      </Card>
    </div>
  );
}

/** search_jobs 结果：横向滚动岗位选择器，选中 + 提交才发送，可查看详情 */
function SearchJobsCard({ segment, interactive, onSend, userReply }: AskCardProps) {
  const { t } = useI18n();
  const jobs = parseJobs(segment.detail);
  const [selected, setSelected] = useState<number | null>(null);
  const [noneFit, setNoneFit] = useState(false);
  const [detailIdx, setDetailIdx] = useState<number | null>(null);
  // 历史回放：从下一条用户消息反推当时提交的岗位 / 「都不符合」
  const history = interactive ? { idx: null, noneFit: false } : parseJobReply(userReply, jobs);
  if (!jobs.length) return null;

  const pickJob = (i: number) => {
    setSelected((prev) => (prev === i ? null : i));
    setNoneFit(false);
  };
  const submit = () => {
    if (selected !== null) {
      const j = jobs[selected];
      // 附岗位 ID：后端据此精确注入蓝本 JD 全文，比标题匹配可靠
      onSend?.(`${OPTION_MARK}我觉得「${j.title}」和我的需求最契合（岗位ID: ${j.job_id}）`);
    } else if (noneFit) {
      onSend?.(`${OPTION_MARK}以上岗位都不太符合我的需求`);
    }
  };

  return (
    <div className="chat-enter my-2 space-y-2">
      <p className="flex items-center gap-1.5 text-label text-on-surface-variant">
        <Icon name="work" size={14} />
        {t("检索到 {n} 个同类岗位，横向滑动查看，选一个最契合的提交", { n: jobs.length })}
      </p>
      <div className="flex snap-x gap-2 overflow-x-auto pb-1">
        {jobs.map((j, i) => {
          const on = selected === i;
          const historyOn = !on && history.idx === i;
          return (
            <div
              key={i}
              onClick={() => interactive && pickJob(i)}
              className={cn(
                "flex w-60 shrink-0 snap-start flex-col rounded-lg border p-3",
                interactive ? "cursor-pointer" : "cursor-default",
                on
                  ? "border-primary bg-primary-container/50"
                  : historyOn
                    ? "border-primary bg-primary-container/50 opacity-70" // 历史回显：选中但禁用
                    : "border-outline-variant bg-surface-lowest"
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="line-clamp-2 text-body font-medium text-on-surface">{j.title}</span>
                {(on || historyOn) && (
                  <Icon name="check_circle" size={18} fill className="shrink-0 text-primary" />
                )}
              </div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                {j.job_category && <StatusChip tone="neutral">{j.job_category}</StatusChip>}
                {j.city_info && <StatusChip tone="neutral">{j.city_info}</StatusChip>}
              </div>
              {j.requirement_excerpt && (
                <p className="mt-1 line-clamp-2 flex-1 text-body-sm text-on-surface-variant">
                  {j.requirement_excerpt}
                </p>
              )}
              <div className="mt-2 flex items-center justify-between">
                {typeof j.score === "number" && (
                  <span className="text-label text-primary">{t("契合 {pct}%", { pct: Math.round(j.score * 100) })}</span>
                )}
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    setDetailIdx(i);
                  }}
                  className="rounded-full px-2 py-0.5 text-label font-medium text-primary hover:bg-primary-container"
                >
                  {t("详情")}
                </button>
              </div>
            </div>
          );
        })}
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          disabled={!interactive}
          onClick={() => {
            if (!interactive) return;
            setNoneFit((v) => !v);
            setSelected(null);
          }}
          className={cn(
            "state-layer rounded-full border px-3 py-1.5 text-body-sm",
            noneFit
              ? "border-primary bg-primary text-on-primary"
              : history.noneFit
                ? "border-primary bg-primary text-on-primary opacity-70 cursor-default" // 历史回显：选中但禁用
                : interactive
                  ? "border-primary/50 bg-surface-lowest text-primary cursor-pointer"
                  : "border-outline-variant text-on-surface-variant/70 cursor-default"
          )}
        >
          {t("以上都不太符合")}
        </button>
        <Button
          variant="filled"
          icon="send"
          className="h-8 px-4"
          disabled={!interactive || (selected === null && !noneFit)}
          onClick={submit}
        >
          {t("提交")}
        </Button>
      </div>
      {detailIdx !== null && <JobDetailDialog job={jobs[detailIdx]} onClose={() => setDetailIdx(null)} />}
    </div>
  );
}

interface Props {
  segment: ToolSegment;
  /** 仅最新消息且空闲时为 true：选项可点；历史/流式中置灰 */
  interactive?: boolean;
  onSend?: (text: string) => void;
  /** 紧随其后的用户消息原文：历史回放时据此回显已选项 */
  userReply?: string;
}

/** 工具调用卡片：运行中 = shaping orb 动效；完成后折叠成一行摘要 */
export default function ToolCallCard({ segment, interactive = false, onSend, userReply }: Props) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const running = !segment.status;
  const failed = segment.status === "error";

  // ask_question 的问题就是消息本体：主色卡片完整展示，选项可点即答
  if (segment.tool === "ask_question" && !failed) {
    return <AskQuestionCard segment={segment} interactive={interactive} onSend={onSend} userReply={userReply} />;
  }

  // search_jobs 命中结果卡片化：点岗位 = 选为提问蓝本
  if (segment.tool === "search_jobs" && !failed && !running && parseJobs(segment.detail).length) {
    return <SearchJobsCard segment={segment} interactive={interactive} onSend={onSend} userReply={userReply} />;
  }
  // 完成但 0 命中（含蓝本兜底拦截）：静默折叠，不渲染卡片
  if (segment.tool === "search_jobs" && !failed && !running) {
    return null;
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
        <span className="font-medium text-on-surface shrink-0">{t(segment.label) || segment.tool}</span>
        <span className="flex-1 min-w-0 truncate text-on-surface-variant">
          {running ? segment.args_summary : failed ? t("失败 · {summary}", { summary: segment.summary ?? "" }) : segment.summary}
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
}
