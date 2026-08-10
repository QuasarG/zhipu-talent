import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import type {
  AcademicReport,
  DimensionScore,
  Evaluation,
  EvidenceItem,
  TrackAssignment,
  TrackEvaluation,
  TrackRecommendation,
} from "@/lib/types";
import { cn } from "@/lib/cn";
import Icon from "@/components/ui/Icon";
import Progress from "@/components/ui/Progress";
import { StatusChip } from "@/components/ui/Chip";
import { resolveTrackWeightPercent, tokenizeEvidenceReferences } from "./scoreOverviewModel";

interface Props {
  evaluation: Evaluation;
  academicReport?: AcademicReport;
}

const DIMENSION_COLORS = [
  "var(--color-track-agent)",
  "var(--color-track-safety)",
  "var(--color-track-ai_infra)",
  "var(--color-track-ai4science)",
  "var(--color-track-multimodal)",
];

function trackColor(track: string) {
  const value = track.toLowerCase();
  if (value.includes("agent")) return "var(--color-track-agent)";
  if (value.includes("safety") || value.includes("安全")) return "var(--color-track-safety)";
  if (value.includes("ai_infra") || value.includes("infra") || value.includes("system")) return "var(--color-track-ai_infra)";
  if (value.includes("science")) return "var(--color-track-ai4science)";
  if (value.includes("multimodal") || value.includes("多模态")) return "var(--color-track-multimodal)";
  return "var(--color-track-base)";
}

interface EvidenceSelection {
  item: EvidenceItem;
  anchor: HTMLElement;
}

export default function ScoreOverview({ evaluation, academicReport }: Props) {
  const report = academicReport || evaluation.academic_report;
  const alignments = report?.alignments || [];
  const evidence = useMemo(() => evaluation.evidence || [], [evaluation.evidence]);
  const evidenceById = useMemo(
    () => new Map(evidence.map((item) => [item.id, item])),
    [evidence],
  );
  const [activeEvidence, setActiveEvidence] = useState<EvidenceSelection | null>(null);
  const openEvidence = (item: EvidenceItem, anchor: HTMLElement) => setActiveEvidence({ item, anchor });

  return (
    <div>
      <header className="pb-5 border-b-2 border-outline-variant">
        <div className="grid grid-cols-[118px_minmax(0,1fr)_auto] items-start gap-4">
          <div>
            <span className="block text-[42px] leading-[44px] font-bold tabular-nums text-primary">{evaluation.overall_score}</span>
            <span className="text-label font-semibold text-on-surface-variant">综合能力分 / 100</span>
          </div>
          <div className="min-w-0">
            <h2 className="text-title-lg font-bold text-on-surface">评估结论</h2>
            <p className="mt-1 text-body font-medium leading-5 text-on-surface">
              <EvidenceText text={evaluation.one_liner || "暂无结论摘要"} evidenceById={evidenceById} onOpen={openEvidence} />
            </p>
            <p className="mt-1 text-label text-on-surface-variant">能力描述用于辅助复核，不代表录取结论</p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <StatusChip tone="info" icon="route">
              路由 {Math.round((evaluation.routing_confidence || 0) * 100)}%
            </StatusChip>
            <StatusChip tone="neutral" icon="description">证据 {evaluation.evidence?.length || 0} 条</StatusChip>
          </div>
        </div>
      </header>

      {!!evaluation.dimension_scores?.length && (
        <ResultSection title="通用能力维度" icon="analytics" count={evaluation.dimension_scores.length}>
          <div className="divide-y divide-outline-variant">
            {evaluation.dimension_scores.map((dimension, index) => (
              <DimensionResult
                key={dimension.key}
                dimension={dimension}
                color={DIMENSION_COLORS[index % DIMENSION_COLORS.length]}
                evidenceById={evidenceById}
                onEvidence={openEvidence}
              />
            ))}
          </div>
        </ResultSection>
      )}

      {!!evaluation.recommended_tracks?.length && (
        <ResultSection title="推荐 Track" icon="alt_route" count={evaluation.recommended_tracks.length}>
          <div className="divide-y-2 divide-outline-variant">
            {evaluation.recommended_tracks.map((track, index) => (
              <TrackResult
                key={`${track.track || track.name}-${index}`}
                recommendation={track}
                evaluation={findTrackEvaluation(track, evaluation.track_evaluations || [])}
                assignment={findTrackAssignment(track, evaluation.track_assignments || [])}
                evidenceById={evidenceById}
                onEvidence={openEvidence}
                index={index}
              />
            ))}
          </div>
        </ResultSection>
      )}

      {!!alignments.length && (
        <ResultSection title="论文核验摘要" icon="fact_check" count={alignments.length}>
          <div className="divide-y divide-outline-variant">
            {alignments.map((alignment, index) => (
              <div key={index} className="grid grid-cols-[28px_minmax(0,1fr)_auto] items-start gap-3 py-3">
                <span className="flex items-center justify-center w-7 h-7 rounded-sm bg-surface-high text-label font-bold tabular-nums text-on-surface-variant">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <div className="min-w-0">
                  <p className="text-body font-bold text-on-surface">{alignment.claim?.title || "未命名论文"}</p>
                  <p className="mt-1 text-body-sm text-on-surface-variant">
                    {alignment.discrepancies?.[0] || alignment.note || "外部记录与简历声明已完成对齐"}
                  </p>
                </div>
                <VerdictBadge verdict={alignment.verdict} humanStatus={alignment.human_status} />
              </div>
            ))}
          </div>
        </ResultSection>
      )}

      <ResultSection title="复核与面谈" icon="forum">
        <ExpandableList title="核心优势" icon="workspace_premium" items={evaluation.core_strengths} evidenceById={evidenceById} onEvidence={openEvidence} defaultOpen />
        <ExpandableList title="潜在风险" icon="warning" items={evaluation.potential_risks} evidenceById={evidenceById} onEvidence={openEvidence} />
        <ExpandableList title="建议面谈问题" icon="quiz" items={evaluation.interview_questions} evidenceById={evidenceById} onEvidence={openEvidence} />
        <ExpandableList title="培养方向" icon="trending_up" items={evaluation.cultivation_direction} evidenceById={evidenceById} onEvidence={openEvidence} />
      </ResultSection>

      {activeEvidence && (
        <EvidencePopover selection={activeEvidence} onClose={() => setActiveEvidence(null)} />
      )}
    </div>
  );
}

function DimensionResult({ dimension, color, evidenceById, onEvidence }: {
  dimension: DimensionScore;
  color: string;
  evidenceById: Map<string, EvidenceItem>;
  onEvidence: (item: EvidenceItem, anchor: HTMLElement) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  // score 是 LLM 原始 0-5 分，展示必须用 weighted_score 对齐 max_points 量纲
  const percentage = dimension.max_points > 0
    ? Math.min(100, dimension.weighted_score / dimension.max_points * 100)
    : 0;
  const hasLongRationale = dimension.rationale.length > 110;

  return (
    <article className="grid grid-cols-[140px_minmax(0,1fr)_72px] items-start gap-4 py-4">
      <div className="min-w-0 pt-0.5">
        <p className="text-body font-bold leading-5 text-on-surface">{dimension.label}</p>
        <p className="mt-1 text-label leading-4 text-on-surface-variant break-all">{dimension.key}</p>
      </div>
      <div className="min-w-0">
        <Progress value={percentage} color={color} />
        {dimension.rationale && (
          <p className={cn(
            "mt-2 text-body-sm leading-5 text-on-surface-variant",
            !expanded && "line-clamp-3",
          )}>
            <EvidenceText text={dimension.rationale} evidenceById={evidenceById} onOpen={onEvidence} />
          </p>
        )}
        <div className="flex items-start justify-between gap-3 mt-2">
          <EvidenceReferenceList ids={dimension.evidence_ids} evidenceById={evidenceById} onOpen={onEvidence} />
          {hasLongRationale && (
            <button
              type="button"
              className="shrink-0 text-label font-bold text-primary hover:underline focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-2"
              onClick={() => setExpanded((value) => !value)}
              aria-expanded={expanded}
            >
              {expanded ? "收起" : "展开全文"}
            </button>
          )}
        </div>
      </div>
      <span className="pt-0.5 text-body font-bold tabular-nums text-right text-on-surface">
        {dimension.weighted_score}<span className="font-normal text-on-surface-variant"> / {dimension.max_points}</span>
      </span>
    </article>
  );
}

function ResultSection({ title, icon, count, children }: { title: string; icon: string; count?: number; children: ReactNode }) {
  return (
    <section className="py-5 border-b-2 last:border-b-0 border-outline-variant">
      <div className="flex items-center gap-2 mb-3">
        <Icon name={icon} size={19} className="text-primary" />
        <h3 className="text-title-lg font-bold text-on-surface">{title}</h3>
        {count !== undefined && <span className="ml-auto text-label font-semibold text-on-surface-variant">{count} 项</span>}
      </div>
      {children}
    </section>
  );
}

function TrackResult({ recommendation, evaluation, assignment, evidenceById, onEvidence, index }: {
  recommendation: TrackRecommendation;
  evaluation?: TrackEvaluation;
  assignment?: TrackAssignment;
  evidenceById: Map<string, EvidenceItem>;
  onEvidence: (item: EvidenceItem, anchor: HTMLElement) => void;
  index: number;
}) {
  const [open, setOpen] = useState(index === 0);
  const track = recommendation.track || recommendation.name || "未命名 Track";
  const weightPercent = resolveTrackWeightPercent(
    recommendation.weight,
    assignment?.weight || evaluation?.weight,
  );
  const color = trackColor(track);
  const rationale = assignment?.rationale || recommendation.rationale || recommendation.reason || "无路由说明";
  const evidenceIds = uniqueIds([
    ...(recommendation.evidence_ids || []),
    ...(assignment?.evidence_ids || []),
    ...(evaluation?.evidence_ids || []),
  ]);

  return (
    <article>
      <button
        type="button"
        className="state-layer grid grid-cols-[28px_minmax(0,1fr)_74px_24px] items-center gap-3 w-full py-3 text-left rounded-sm"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="flex items-center justify-center w-7 h-7 rounded-sm text-label font-bold text-white" style={{ backgroundColor: color }}>
          {String(index + 1).padStart(2, "0")}
        </span>
        <span className="min-w-0">
          <span className="block text-title font-bold text-on-surface truncate">{track}</span>
          <span className="block mt-0.5 text-label text-on-surface-variant truncate">
            <EvidenceText text={recommendation.rationale || recommendation.reason || rationale} evidenceById={evidenceById} onOpen={onEvidence} />
          </span>
        </span>
        <span className="text-right">
          <span className="block text-title font-bold tabular-nums" style={{ color }}>{weightPercent}%</span>
          <span className="block text-label text-on-surface-variant">组合权重</span>
        </span>
        <Icon name="expand_more" size={20} className={cn("text-on-surface-variant transition-transform duration-300 ease-emphasized", open && "rotate-180")} />
      </button>
      <div className="process-collapse" data-open={open}>
        <div>
          <div className="ml-10 pb-4">
            <Progress value={weightPercent} color={color} />
            {evaluation ? (
              <div className="mt-3 border-l-2 border-outline-variant pl-4">
                <div className="grid grid-cols-3 gap-3 pb-3">
                  <Metric label="原始分" value={formatScore(evaluation.raw_score)} />
                  <Metric label="校准分" value={formatScore(evaluation.calibrated_score)} strong />
                  <Metric label="置信度" value={`${Math.round(evaluation.confidence * 100)}%`} />
                </div>
                <div className="pb-3 border-t border-outline-variant pt-3">
                  <p className="text-label font-bold text-on-surface-variant">路由理由</p>
                  <p className="mt-1 text-body-sm leading-5 text-on-surface">
                    <EvidenceText text={rationale} evidenceById={evidenceById} onOpen={onEvidence} />
                  </p>
                  <EvidenceReferenceList ids={evidenceIds} evidenceById={evidenceById} onOpen={onEvidence} className="mt-2" />
                </div>
                {!!evaluation.dimension_scores.length && (
                  <div className="divide-y divide-outline-variant border-t border-outline-variant">
                    {evaluation.dimension_scores.map((dimension) => (
                      <div key={dimension.key} className="grid grid-cols-[112px_minmax(0,1fr)_56px] items-start gap-3 py-3">
                        <span className="text-body-sm font-semibold leading-5 text-on-surface">{dimension.label}</span>
                        <div className="min-w-0">
                          <Progress value={dimension.max_points ? Math.min(100, dimension.weighted_score / dimension.max_points * 100) : 0} color={color} />
                          {dimension.rationale && (
                            <p className="mt-1.5 text-label leading-5 text-on-surface-variant">
                              <EvidenceText text={dimension.rationale} evidenceById={evidenceById} onOpen={onEvidence} />
                            </p>
                          )}
                          <EvidenceReferenceList ids={dimension.evidence_ids} evidenceById={evidenceById} onOpen={onEvidence} className="mt-1.5" />
                        </div>
                        <span className="text-body-sm font-bold tabular-nums text-right">{dimension.weighted_score}/{dimension.max_points}</span>
                      </div>
                    ))}
                  </div>
                )}
                {!!evaluation.risk_notes.length && (
                  <div className="mt-3 border-l-2 border-warning pl-3">
                    <p className="text-label font-bold text-warning">Track 风险</p>
                    {evaluation.risk_notes.map((risk, riskIndex) => (
                      <p key={riskIndex} className="mt-1 text-body-sm text-on-surface-variant">
                        <EvidenceText text={risk} evidenceById={evidenceById} onOpen={onEvidence} />
                      </p>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <p className="mt-2 text-body-sm text-on-surface-variant">该 Track 暂无独立评分明细。</p>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}

function Metric({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div>
      <span className="block text-label font-medium text-on-surface-variant">{label}</span>
      <span className={cn("block mt-0.5 text-title tabular-nums", strong ? "font-bold text-primary" : "font-semibold text-on-surface")}>{value}</span>
    </div>
  );
}

function formatScore(value: number) {
  return Number.isFinite(value) ? value.toFixed(1) : "-";
}

function findTrackEvaluation(recommendation: TrackRecommendation, evaluations: TrackEvaluation[]) {
  const track = (recommendation.track || recommendation.name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  return evaluations.find((evaluation) => {
    const candidate = `${evaluation.track}${evaluation.label}`.toLowerCase().replace(/[^a-z0-9]/g, "");
    return candidate.includes(track) || track.includes(evaluation.track.toLowerCase().replace(/[^a-z0-9]/g, ""));
  });
}

function findTrackAssignment(recommendation: TrackRecommendation, assignments: TrackAssignment[]) {
  const track = (recommendation.track || recommendation.name || "").toLowerCase();
  return assignments.find((assignment) => assignment.track.toLowerCase() === track);
}

function uniqueIds(ids: string[]) {
  return [...new Set(ids.filter(Boolean))];
}

function EvidenceText({ text, evidenceById, onOpen }: {
  text: string;
  evidenceById: Map<string, EvidenceItem>;
  onOpen: (item: EvidenceItem, anchor: HTMLElement) => void;
}) {
  const parts = tokenizeEvidenceReferences(text, new Set(evidenceById.keys()));
  return (
    <>
      {parts.map((part, index) => part.kind === "evidence" && part.evidenceId ? (
        <button
          key={`${part.evidenceId}-${index}`}
          type="button"
          className="inline border-0 border-b border-dashed border-primary bg-transparent px-0.5 text-primary font-semibold cursor-pointer hover:bg-primary-container focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-2"
          onClick={(event) => {
            const item = evidenceById.get(part.evidenceId!);
            if (item) onOpen(item, event.currentTarget);
          }}
          title={`查看 ${part.evidenceId} 证据`}
        >
          {part.text}
        </button>
      ) : (
        <span key={`text-${index}`}>{part.text}</span>
      ))}
    </>
  );
}

function EvidenceReferenceList({ ids, evidenceById, onOpen, className }: {
  ids?: string[];
  evidenceById: Map<string, EvidenceItem>;
  onOpen: (item: EvidenceItem, anchor: HTMLElement) => void;
  className?: string;
}) {
  const items = uniqueIds(ids || [])
    .map((id) => evidenceById.get(id))
    .filter((item): item is EvidenceItem => !!item);
  if (!items.length) return null;
  return (
    <div className={cn("flex flex-wrap items-center gap-x-2 gap-y-1", className)}>
      <span className="text-label font-bold text-on-surface-variant">证据</span>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          className="border-0 border-b border-dashed border-primary bg-transparent px-0.5 text-label font-bold text-primary cursor-pointer hover:bg-primary-container focus-visible:outline-2 focus-visible:outline-primary focus-visible:outline-offset-2"
          onClick={(event) => onOpen(item, event.currentTarget)}
          title={`查看 ${item.id} 证据`}
        >
          {item.id}
        </button>
      ))}
    </div>
  );
}

function EvidencePopover({ selection, onClose }: { selection: EvidenceSelection; onClose: () => void }) {
  const popoverRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  useLayoutEffect(() => {
    const anchor = selection.anchor;
    const updatePosition = () => {
      const rect = anchor.getBoundingClientRect();
      const popover = popoverRef.current;
      const width = Math.min(360, window.innerWidth - 24);
      const height = popover?.getBoundingClientRect().height || 320;
      const left = Math.min(Math.max(12, rect.left), window.innerWidth - width - 12);
      const below = rect.bottom + 10;
      const top = below + height <= window.innerHeight - 12
        ? below
        : Math.max(12, rect.top - height - 10);
      setPosition({ top, left });
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [selection]);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!popoverRef.current?.contains(target) && !selection.anchor.contains(target)) onClose();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose, selection.anchor]);

  if (typeof document === "undefined") return null;
  return createPortal(
    <div
      ref={popoverRef}
      role="dialog"
      aria-label={`${selection.item.id} 证据详情`}
      className="fixed z-[100] w-[min(360px,calc(100vw-24px))] max-h-[min(520px,calc(100vh-24px))] overflow-y-auto rounded-md border border-primary bg-surface-lowest shadow-xl"
      style={{
        top: position?.top ?? 12,
        left: position?.left ?? 12,
        visibility: position ? "visible" : "hidden",
      }}
    >
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-outline-variant bg-primary-container">
        <div className="min-w-0">
          <p className="text-label font-bold uppercase tracking-[0.08em] text-primary">{selection.item.id}</p>
          <h3 className="mt-0.5 text-title font-bold text-on-surface truncate">{selection.item.dimension || "证据详情"}</h3>
        </div>
        <button
          type="button"
          autoFocus
          className="flex items-center justify-center w-8 h-8 rounded-full text-on-surface-variant hover:bg-surface-high focus-visible:outline-2 focus-visible:outline-primary"
          onClick={onClose}
          aria-label="关闭证据详情"
        >
          <Icon name="close" size={18} />
        </button>
      </div>
      <div className="space-y-3 px-4 py-4 text-body-sm text-on-surface">
        <div className="grid grid-cols-[52px_minmax(0,1fr)] gap-x-3 gap-y-2">
          <span className="text-label font-bold text-on-surface-variant">来源</span>
          <span className="break-words">{selection.item.source || "未标注"}</span>
          {selection.item.page !== null && selection.item.page !== undefined && (
            <>
              <span className="text-label font-bold text-on-surface-variant">页码</span>
              <span>P{selection.item.page}</span>
            </>
          )}
        </div>
        <blockquote className="m-0 border-l-2 border-primary bg-surface-low px-3 py-2.5 leading-6 break-words">
          {selection.item.quote || "无原文摘录"}
        </blockquote>
        {!!selection.item.signals?.length && (
          <div className="flex flex-wrap gap-1.5">
            {selection.item.signals.map((signal) => <StatusChip key={signal} tone="info" size="sm">{signal}</StatusChip>)}
          </div>
        )}
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-label text-on-surface-variant">
          <span>证据强度 <strong className="text-on-surface">{selection.item.strength}/5</strong></span>
          {selection.item.has_metric && <span>含量化指标</span>}
          {selection.item.has_specific_tool && <span>含具体工具</span>}
          {selection.item.has_ownership && <span>含负责边界</span>}
        </div>
      </div>
    </div>,
    document.body,
  );
}

function ExpandableList({ title, icon, items, evidenceById, onEvidence, defaultOpen = false }: {
  title: string;
  icon: string;
  items?: string[];
  evidenceById: Map<string, EvidenceItem>;
  onEvidence: (item: EvidenceItem, anchor: HTMLElement) => void;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (!items?.length) return null;
  return (
    <div className="border-t first:border-t-0 border-outline-variant">
      <button
        type="button"
        className="state-layer flex items-center gap-2 w-full min-h-11 py-2 text-left rounded-sm"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <Icon name={icon} size={17} className="text-on-surface-variant" />
        <span className="text-body font-bold text-on-surface">{title}</span>
        <span className="text-label text-on-surface-variant">{items.length} 项</span>
        <Icon name="expand_more" size={19} className={cn("ml-auto text-on-surface-variant transition-transform duration-300 ease-emphasized", open && "rotate-180")} />
      </button>
      <div className="process-collapse" data-open={open}>
        <div>
          <ol className="pb-3 pl-7 space-y-2">
            {items.map((item, index) => (
              <li key={index} className="grid grid-cols-[20px_minmax(0,1fr)] gap-2 text-body-sm leading-5 text-on-surface-variant">
                <span className="font-bold tabular-nums text-on-surface">{String(index + 1).padStart(2, "0")}</span>
                <span><EvidenceText text={item} evidenceById={evidenceById} onOpen={onEvidence} /></span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}

function VerdictBadge({ verdict, humanStatus }: {
  verdict: "verified" | "mismatch" | "unverifiable";
  humanStatus?: "unreviewed" | "confirmed" | "dismissed";
}) {
  if (humanStatus === "confirmed") return <StatusChip tone="success" variant="filled" icon="person_check">人工通过</StatusChip>;
  if (humanStatus === "dismissed") return <StatusChip tone="error" variant="filled" icon="person_cancel">人工驳回</StatusChip>;
  if (verdict === "verified") return <StatusChip tone="success" variant="filled" icon="verified">通过</StatusChip>;
  if (verdict === "mismatch") return <StatusChip tone="error" variant="filled" icon="error">冲突</StatusChip>;
  return <StatusChip tone="warning" variant="filled" icon="help">待人工</StatusChip>;
}
