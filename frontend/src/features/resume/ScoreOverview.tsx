import type { Evaluation } from "@/lib/types";
import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";

interface Props {
  evaluation: Evaluation;
}

const DIM_COLORS = ["#2F7D73", "#3B82F6", "#B7791F", "#3B9A8E", "#D45D54"];

export default function ScoreOverview({ evaluation: ev }: Props) {
  return (
    <div>
      {/* 能力总览 */}
      <section className="mb-5">
        <div className="flex items-baseline gap-4 flex-wrap">
          <div className="flex items-baseline gap-1">
            <span className="text-5xl font-bold leading-none">{ev.overall_score}</span>
            <span className="text-sm text-ink-secondary">/ 100</span>
          </div>
          <div className="flex-1 min-w-[120px]">
            <p className="font-medium text-sm">能力总分</p>
            <p className="text-[10px] text-ink-muted mt-0.5">仅用于能力描述，不代表录取结论</p>
          </div>
          <div className="flex gap-2 flex-wrap">
            {ev.routing_confidence > 0 && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-blue-soft text-blue">
                路由置信度 {(ev.routing_confidence * 100).toFixed(0)}%
              </span>
            )}
            {ev.evidence?.length > 0 && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-surface-mist text-ink-secondary">
                证据 {ev.evidence.length} 条
              </span>
            )}
          </div>
        </div>
      </section>

      {/* 分维度条形图 */}
      {ev.dimension_scores?.length > 0 && (
        <section className="mb-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-secondary mb-3 pb-2 border-b border-ink/10">
            能力维度
          </h3>
          <div className="flex flex-col gap-3">
            {ev.dimension_scores.map((d, i) => {
              const pct = d.max_points > 0 ? (d.score / d.max_points) * 100 : 0;
              return (
                <div key={d.key} className="grid grid-cols-[100px_1fr_50px] items-center gap-3">
                  <span className="text-xs truncate">{d.label}</span>
                  <div className="h-2 rounded-full bg-surface-mist overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-300"
                      style={{ width: `${pct}%`, background: DIM_COLORS[i % DIM_COLORS.length] }}
                    />
                  </div>
                  <span className="text-xs text-ink-secondary text-right font-mono">
                    {d.score}/{d.max_points}
                  </span>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Track 推荐 */}
      {ev.recommended_tracks?.length > 0 && (
        <section className="mb-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-secondary pb-2 border-b border-ink/10 flex-1">
              推荐 Track
            </h3>
            {ev.routing_confidence > 0 && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-surface-mist text-ink-secondary">
                路由置信度 {(ev.routing_confidence * 100).toFixed(0)}%
              </span>
            )}
          </div>
          <div className="flex flex-col gap-3">
            {ev.recommended_tracks.map((t, i) => {
              const track = t.track || t.name || "";
              const weight = t.weight || 0;
              const pct = (weight * 100).toFixed(0);
              return (
                <div key={i} className="py-1">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-medium">{track}</span>
                    <span className="text-xs text-teal font-mono">{pct}%</span>
                  </div>
                  <div className="h-1 rounded-full bg-surface-mist overflow-hidden mb-1">
                    <div className="h-full rounded-full bg-teal transition-all duration-300" style={{ width: `${pct}%` }} />
                  </div>
                  {(t.rationale || t.reason) && (
                    <p className="text-xs text-ink-secondary leading-relaxed">{t.rationale || t.reason}</p>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* 研究组匹配（独立横条） */}
      <section className="mb-5">
        <div
          className={cn(
            "flex items-center justify-between gap-4 px-4 py-3 rounded-[10px] border",
            ev.research_group_matching_status === "not_configured"
              ? "bg-surface-mist border-ink/10"
              : "bg-surface-paper border-ink/10"
          )}
        >
          <div>
            <h3 className="text-sm font-medium mb-1">研究组匹配</h3>
            <span className="text-xs px-2 py-0.5 rounded-full bg-surface-mist text-ink-secondary">
              {ev.research_group_matching_status === "not_configured" ? "尚未配置研究组要求" : ev.research_group_matching_status}
            </span>
          </div>
          <p className="text-[10px] text-right max-w-[180px] text-ink-muted">
            Track 推荐不等于具体研究组匹配
          </p>
        </div>
      </section>

      {/* 论文核验 */}
      {ev.academic_report?.alignments?.length > 0 && (
        <section className="mb-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-secondary mb-3 pb-2 border-b border-ink/10">
            论文状态与作者顺序核验
          </h3>
          <div className="flex flex-col gap-3">
            {ev.academic_report.alignments.map((al, i) => (
              <div key={i} className="p-3 rounded-[10px] bg-surface-paper border border-ink/10">
                <div className="text-sm font-medium mb-2">
                  {al.claim?.title || al.claim_title || "未命名论文"}
                </div>
                <div className="grid grid-cols-2 gap-3 mb-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[10px] w-full text-ink-muted mb-0.5">自述</span>
                    <VerifyBadge verdict={al.verdict} status={al.claim?.claimed_status} />
                    {al.claim?.claimed_role && (
                      <span className="text-[10px] px-2 py-0.5 rounded-full bg-surface-mist text-ink-secondary">
                        {al.claim.claimed_role}
                      </span>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[10px] w-full text-ink-muted mb-0.5">外部核验</span>
                    <VerdictBadge verdict={al.verdict} />
                  </div>
                </div>
                {al.matched_title && <p className="text-xs text-ink-secondary">匹配：{al.matched_title}</p>}
                {al.discrepancies?.length > 0 && (
                  <div className="mt-2">
                    {al.discrepancies.map((d, j) => (
                      <p key={j} className="text-xs text-coral py-0.5">{d}</p>
                    ))}
                  </div>
                )}
                {al.openalex_url && (
                  <a href={al.openalex_url} target="_blank" rel="noopener" className="text-xs text-blue mt-1 inline-block">
                    OpenAlex 来源
                  </a>
                )}
              </div>
            ))}
          </div>
          {ev.academic_report.warnings?.length > 0 && (
            <div className="mt-2">
              {ev.academic_report.warnings.map((w, i) => (
                <p key={i} className="text-xs text-ink-secondary py-0.5">{w}</p>
              ))}
            </div>
          )}
        </section>
      )}

      {/* 可折叠：核心优势 / 潜在风险 / 面谈问题 */}
      <Collapsible title="核心优势" items={ev.core_strengths} />
      <Collapsible title="潜在风险" items={ev.potential_risks} />
      <Collapsible title="建议面谈问题" items={ev.interview_questions} />
    </div>
  );
}

function Collapsible({ title, items }: { title: string; items?: string[] }) {
  const [open, setOpen] = useState(false);
  if (!items?.length) return null;
  return (
    <details className="mb-3 rounded-[10px] bg-surface-paper border border-ink/10 overflow-hidden" open={open}>
      <summary
        className="px-4 py-3 text-sm font-medium cursor-pointer flex items-center gap-2 list-none"
        onClick={(e) => { e.preventDefault(); setOpen(!open); }}
      >
        {title}
        <span className="text-xs text-ink-secondary">({items.length})</span>
        <ChevronDown size={16} className={cn("ml-auto transition-transform", open && "rotate-180")} />
      </summary>
      <div className="px-4 pb-3">
        {items.map((item, i) => (
          <p key={i} className="text-xs leading-relaxed py-0.5 text-ink-secondary">{item}</p>
        ))}
      </div>
    </details>
  );
}

function VerifyBadge({ verdict, status }: { verdict: string; status?: string }) {
  const s = (status || "").toLowerCase();
  const cls =
    s.includes("published") || s.includes("已发表") ? "bg-teal-soft text-teal" :
    s.includes("review") || s.includes("在审") || s.includes("submit") || s.includes("投稿") || s.includes("在投") ? "bg-amber-soft text-amber-glow" :
    "bg-surface-mist text-ink-secondary";
  const label =
    s.includes("published") || s.includes("已发表") ? "已发表" :
    s.includes("review") || s.includes("在审") ? "在审" :
    s.includes("submit") || s.includes("投稿") || s.includes("在投") ? "已投稿" :
    s.includes("accept") || s.includes("接收") ? "已接收" : status || "未说明";
  return <span className={cn("text-[10px] px-2 py-0.5 rounded-full", cls)}>{label}</span>;
}

function VerdictBadge({ verdict }: { verdict: string }) {
  const v = (verdict || "").toLowerCase();
  if (v === "verified") return <span className="text-[10px] px-2 py-0.5 rounded-full bg-teal-soft text-teal">已核验</span>;
  if (v === "mismatch") return <span className="text-[10px] px-2 py-0.5 rounded-full bg-coral-soft text-coral">存在冲突</span>;
  return <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-soft text-amber-glow">待核查</span>;
}
