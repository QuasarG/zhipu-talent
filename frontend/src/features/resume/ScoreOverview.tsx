import type { ReactNode } from "react";
import type { Evaluation } from "@/lib/types";
import { useState } from "react";
import { cn } from "@/lib/cn";
import Icon from "@/components/ui/Icon";
import Progress from "@/components/ui/Progress";
import { StatusChip } from "@/components/ui/Chip";

interface Props {
  evaluation: Evaluation;
}

// 维度条配色：循环使用 track 语义 token
const DIM_TRACK_COLORS = [
  "var(--color-track-agent)",
  "var(--color-track-safety)",
  "var(--color-track-systems)",
  "var(--color-track-ai4science)",
  "var(--color-track-multimodal)",
];

// track 名称 → 对应语义色 token
function trackColor(track: string): string {
  const t = track.toLowerCase();
  if (t.includes("agent")) return "var(--color-track-agent)";
  if (t.includes("safety") || t.includes("安全")) return "var(--color-track-safety)";
  if (t.includes("system")) return "var(--color-track-systems)";
  if (t.includes("science") || t.includes("ai4science")) return "var(--color-track-ai4science)";
  if (t.includes("multimodal") || t.includes("多模态")) return "var(--color-track-multimodal)";
  return "var(--color-track-base)";
}

export default function ScoreOverview({ evaluation: ev }: Props) {
  const report = ev.academic_report;
  return (
    <div>
      {/* 能力总览 */}
      <section className="mb-5">
        <div className="flex items-start gap-4 flex-wrap">
          <div className="flex items-baseline gap-1">
            <span className="text-display text-primary">{ev.overall_score}</span>
            <span className="text-body-sm text-on-surface-variant">/ 100</span>
          </div>
          <div className="flex-1 min-w-[120px]">
            <p className="text-title">能力总分</p>
            <p className="text-label text-on-surface-variant mt-0.5">仅用于能力描述，不代表录取结论</p>
          </div>
          <div className="flex flex-col items-end gap-1.5">
            {ev.routing_confidence > 0 && (
              <StatusChip tone="info" icon="verified">
                路由置信度 {(ev.routing_confidence * 100).toFixed(0)}%
              </StatusChip>
            )}
            {ev.evidence?.length > 0 && (
              <StatusChip tone="neutral" icon="description">
                证据 {ev.evidence.length} 条
              </StatusChip>
            )}
          </div>
        </div>
      </section>

      {/* 分维度条形图 */}
      {ev.dimension_scores?.length > 0 && (
        <section className="mb-5">
          <SectionTitle>能力维度</SectionTitle>
          <div className="flex flex-col gap-3">
            {ev.dimension_scores.map((d, i) => {
              const pct = d.max_points > 0 ? (d.score / d.max_points) * 100 : 0;
              return (
                <div key={d.key} className="grid grid-cols-[96px_minmax(0,1fr)_52px] items-center gap-3">
                  <span className="text-body-sm truncate">{d.label}</span>
                  <Progress value={pct} color={DIM_TRACK_COLORS[i % DIM_TRACK_COLORS.length]} />
                  <span className="text-body-sm text-on-surface-variant text-right font-mono">
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
          <div className="flex items-center justify-between gap-2 mb-3 pb-2 border-b border-outline-variant">
            <h3 className="text-label uppercase tracking-wider text-on-surface-variant">推荐 Track</h3>
            {ev.routing_confidence > 0 && (
              <StatusChip tone="neutral">
                路由置信度 {(ev.routing_confidence * 100).toFixed(0)}%
              </StatusChip>
            )}
          </div>
          <div className="flex flex-col gap-3">
            {ev.recommended_tracks.map((t, i) => {
              const track = t.track || t.name || "";
              const weight = t.weight || 0;
              const pct = (weight * 100).toFixed(0);
              const color = trackColor(track);
              return (
                <div key={i} className="py-1">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="flex items-center gap-2 min-w-0">
                      <span className="text-body-sm text-on-surface-variant w-4 shrink-0">{i + 1}</span>
                      <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
                      <span className="text-title truncate">{track}</span>
                    </span>
                    <span className="text-body-sm font-mono shrink-0" style={{ color }}>{pct}%</span>
                  </div>
                  <Progress value={weight * 100} color={color} className="mb-1" />
                  {(t.rationale || t.reason) && (
                    <p className="text-body-sm text-on-surface-variant leading-relaxed">{t.rationale || t.reason}</p>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* 研究组匹配（独立横条） */}
      <section className="mb-5">
        <div className="flex items-center justify-between gap-4 px-4 py-3 rounded-md bg-surface-lowest border border-outline-variant">
          <div className="flex items-center gap-3 min-w-0">
            <Icon name="groups" size={20} className="text-on-surface-variant shrink-0" />
            <div className="min-w-0">
              <h3 className="text-title mb-1">研究组匹配</h3>
              <StatusChip tone="neutral">
                {ev.research_group_matching_status === "not_configured" ? "尚未配置研究组要求" : ev.research_group_matching_status}
              </StatusChip>
            </div>
          </div>
          <p className="text-label text-right max-w-[180px] text-on-surface-variant shrink-0">
            Track 推荐不等于具体研究组匹配
          </p>
        </div>
      </section>

      {/* 论文核验 */}
      {report && report.alignments.length > 0 && (
        <section className="mb-5">
          <SectionTitle>论文状态与作者顺序核验</SectionTitle>
          <div className="flex flex-col gap-3">
            {report.alignments.map((al, i) => (
              <div key={i} className="p-3 rounded-md bg-surface-lowest border border-outline-variant">
                <div className="text-title mb-2">
                  {al.claim?.title || al.claim_title || "未命名论文"}
                </div>
                <div className="grid grid-cols-2 gap-3 mb-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-label w-full text-on-surface-variant mb-0.5">自述</span>
                    <VerifyBadge status={al.claim?.claimed_status} />
                    {al.claim?.claimed_role && (
                      <StatusChip tone="neutral">{al.claim.claimed_role}</StatusChip>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-label w-full text-on-surface-variant mb-0.5">外部核验</span>
                    <VerdictBadge verdict={al.verdict} />
                  </div>
                </div>
                {al.matched_title && <p className="text-body-sm text-on-surface-variant">匹配：{al.matched_title}</p>}
                {al.discrepancies && al.discrepancies.length > 0 && (
                  <div className="mt-2">
                    {al.discrepancies.map((d, j) => (
                      <p key={j} className="text-body-sm text-error py-0.5">{d}</p>
                    ))}
                  </div>
                )}
                {al.openalex_url && (
                  <a
                    href={al.openalex_url}
                    target="_blank"
                    rel="noopener"
                    className="state-layer inline-flex items-center gap-1 text-body-sm text-primary mt-1 px-1 -mx-1 rounded-xs"
                  >
                    OpenAlex 来源
                    <Icon name="open_in_new" size={14} />
                  </a>
                )}
              </div>
            ))}
          </div>
          {report.warnings.length > 0 && (
            <div className="mt-2">
              {report.warnings.map((w, i) => (
                <p key={i} className="text-body-sm text-on-surface-variant py-0.5">{w}</p>
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

function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h3 className="text-label uppercase tracking-wider text-on-surface-variant mb-3 pb-2 border-b border-outline-variant">
      {children}
    </h3>
  );
}

function Collapsible({ title, items }: { title: string; items?: string[] }) {
  const [open, setOpen] = useState(false);
  if (!items?.length) return null;
  return (
    <details className="mb-3 rounded-md bg-surface-lowest border border-outline-variant overflow-hidden" open={open}>
      <summary
        className="state-layer px-4 py-3 text-title cursor-pointer flex items-center gap-2 list-none"
        onClick={(e) => { e.preventDefault(); setOpen(!open); }}
      >
        {title}
        <span className="text-body-sm text-on-surface-variant">({items.length})</span>
        <Icon name="expand_more" size={18} className={cn("ml-auto text-on-surface-variant transition-transform", open && "rotate-180")} />
      </summary>
      <div className="px-4 pb-3">
        {items.map((item, i) => (
          <p key={i} className="text-body-sm leading-relaxed py-0.5 text-on-surface-variant">{item}</p>
        ))}
      </div>
    </details>
  );
}

function VerifyBadge({ status }: { status?: string }) {
  const s = (status || "").toLowerCase();
  const tone =
    s.includes("published") || s.includes("已发表") ? "success" :
    s.includes("review") || s.includes("在审") || s.includes("submit") || s.includes("投稿") || s.includes("在投") ? "warning" :
    "neutral";
  const label =
    s.includes("published") || s.includes("已发表") ? "已发表" :
    s.includes("review") || s.includes("在审") ? "在审" :
    s.includes("submit") || s.includes("投稿") || s.includes("在投") ? "已投稿" :
    s.includes("accept") || s.includes("接收") ? "已接收" : status || "未说明";
  return <StatusChip tone={tone}>{label}</StatusChip>;
}

function VerdictBadge({ verdict }: { verdict: string }) {
  const v = (verdict || "").toLowerCase();
  if (v === "verified") return <StatusChip tone="success" icon="check_circle">已核验</StatusChip>;
  if (v === "mismatch") return <StatusChip tone="error" variant="filled" icon="error">存在冲突</StatusChip>;
  return <StatusChip tone="warning" icon="pending">待核查</StatusChip>;
}
