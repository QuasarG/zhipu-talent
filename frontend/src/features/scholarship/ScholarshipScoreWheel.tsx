import { useEffect, useState } from "react";
import type { ScholarshipEvaluation } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/cn";
import Icon from "@/components/ui/Icon";
import { StatusChip } from "@/components/ui/Chip";
import { fmtScore } from "./scholarshipModel";

type Dimension = ScholarshipEvaluation["dimensions"][number];
const DIMENSION_NAMES: Record<string, string> = {
  academic_impact: "学术成果与影响力",
  originality: "原创能力与生态贡献",
  independence: "独立研究与技术工程能力",
  letter_endorsement: "导师评价",
  integrity_risk: "材料真实性与学术诚信",
};
const COLORS = ["#222B3A", "#4676A9", "#4B9078", "#C18A30", "#8565A7"];
const SIZE = 300;
const RADIUS = 112;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export default function ScholarshipScoreWheel({ evaluation }: { evaluation: ScholarshipEvaluation }) {
  const { t } = useI18n();
  const [selectedKey, setSelectedKey] = useState(evaluation.dimensions[0]?.key ?? "");
  useEffect(() => { setSelectedKey(evaluation.dimensions[0]?.key ?? ""); }, [evaluation.id, evaluation.dimensions]);
  const selected = evaluation.dimensions.find((dimension) => dimension.key === selectedKey) ?? evaluation.dimensions[0];
  const totalWeight = evaluation.dimensions.reduce((sum, dimension) => sum + Math.max(0, dimension.max_points), 0) || 100;
  let offset = 0;
  const segments = evaluation.dimensions.map((dimension, index) => {
    const length = CIRCUMFERENCE * Math.max(0, dimension.max_points) / totalWeight;
    const start = offset;
    offset += length;
    return { dimension, index, start, length, color: COLORS[index % COLORS.length] };
  });

  return (
    <div className="grid h-[860px] min-h-0 grid-rows-[470px_minmax(0,1fr)] gap-5 overflow-hidden p-4 md:h-[560px] md:grid-cols-[minmax(290px,0.9fr)_minmax(0,1.1fr)] md:grid-rows-1 md:items-center md:p-6">
      <div className="flex min-h-0 flex-col items-center justify-center gap-3">
        <div className="relative size-[300px] shrink-0" role="group" aria-label={t("评分维度圆环")}>
          <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="size-full -rotate-90" aria-hidden="true">
            {segments.map(({ dimension, start, length, color }) => {
              const gap = Math.min(5, length * 0.12);
              const capacity = Math.max(0, length - gap);
              const earned = capacity * Math.max(0, Math.min(1, dimension.score / Math.max(1, dimension.max_points)));
              const active = selected?.key === dimension.key;
              return (
                <g key={dimension.key}>
                  <circle cx={150} cy={150} r={RADIUS} fill="none" stroke={color} strokeOpacity={active ? 0.23 : 0.13} strokeWidth={active ? 31 : 27}
                    onClick={() => setSelectedKey(dimension.key)} className="scholarship-score-segment cursor-pointer"
                    strokeDasharray={`${capacity} ${CIRCUMFERENCE - capacity}`} strokeDashoffset={-start} />
                  <circle cx={150} cy={150} r={RADIUS} fill="none" stroke={color} strokeWidth={active ? 31 : 27}
                    onClick={() => setSelectedKey(dimension.key)} className="scholarship-score-segment cursor-pointer"
                    strokeDasharray={`${earned} ${CIRCUMFERENCE - earned}`} strokeDashoffset={-start} />
                </g>
              );
            })}
          </svg>
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-label text-on-surface-variant">{t("综合评分")}</span>
            <span className="font-mono text-[42px] font-semibold leading-tight tabular-nums text-on-surface">{fmtScore(evaluation.blind_score)}</span>
            <span className="text-label text-on-surface-variant">/100</span>
          </div>
          <div className="pointer-events-none absolute inset-0">
            {segments.map(({ dimension, start, length }) => {
              const middle = (start + length / 2) / CIRCUMFERENCE * 2 * Math.PI - Math.PI / 2;
              const x = 150 + Math.cos(middle) * RADIUS;
              const y = 150 + Math.sin(middle) * RADIUS;
              return (
                <button
                  key={dimension.key}
                  type="button"
                  aria-label={t("{name}：{score}/{max}，点击查看评分依据", { name: t(DIMENSION_NAMES[dimension.key] ?? dimension.label), score: fmtScore(dimension.score), max: dimension.max_points })}
                  aria-pressed={selected?.key === dimension.key}
                  onClick={() => setSelectedKey(dimension.key)}
                  className="pointer-events-auto absolute size-12 -translate-x-1/2 -translate-y-1/2 rounded-full focus-visible:outline-2 focus-visible:outline-primary"
                  style={{ left: x, top: y }}
                />
              );
            })}
          </div>
        </div>
        <div className="grid w-full grid-cols-2 gap-1">
          {segments.map(({ dimension, color }) => (
            <button key={dimension.key} type="button" onClick={() => setSelectedKey(dimension.key)}
              aria-pressed={selected?.key === dimension.key}
              className={cn("flex min-w-0 items-start gap-1.5 rounded-md px-2 py-1.5 text-left text-label focus-visible:outline-2 focus-visible:outline-primary", selected?.key === dimension.key ? "bg-primary-container font-semibold text-on-primary-container" : "text-on-surface-variant hover:bg-surface-low")}>
              <span className="size-2.5 shrink-0 rounded-full" style={{ background: color }} />
              <span className="min-w-0">
                <span className="block truncate">{t(DIMENSION_NAMES[dimension.key] ?? dimension.label)}</span>
                <span className="block font-mono tabular-nums opacity-70">{fmtScore(dimension.score)}/{dimension.max_points} · {Math.round(dimension.score / Math.max(1, dimension.max_points) * 100)}%</span>
              </span>
            </button>
          ))}
        </div>
      </div>
      {selected && <DimensionExplanation key={selected.key} dimension={selected} color={segments.find(({ dimension }) => dimension.key === selected.key)?.color ?? COLORS[0]} />}
    </div>
  );
}

function DimensionExplanation({ dimension, color }: { dimension: Dimension; color: string }) {
  const { t } = useI18n();
  return (
    <div className="scholarship-score-detail h-full min-h-0 min-w-0 overflow-y-auto overscroll-contain rounded-xl border border-outline-variant bg-surface p-5 shadow-sm">
      <div className="flex flex-wrap items-start gap-3">
        <span className="mt-1 size-3 shrink-0 rounded-full" style={{ background: color }} />
        <div className="min-w-0 flex-1">
          <h3 className="text-title-lg font-semibold text-on-surface">{t(DIMENSION_NAMES[dimension.key] ?? dimension.label)}</h3>
          {dimension.label_en && <p className="text-label text-on-surface-variant">{dimension.label_en}</p>}
        </div>
        <span className="font-mono text-title-lg font-semibold tabular-nums">{fmtScore(dimension.score)}<span className="text-body-sm text-on-surface-variant">/{dimension.max_points}</span></span>
      </div>
      <div className="mt-4 h-2 overflow-hidden rounded-full bg-surface-high"><div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, dimension.score / Math.max(1, dimension.max_points) * 100))}%`, background: color }} /></div>
      <p className="mt-2 text-label text-on-surface-variant">{t("该维度得分占其满分的 {percent}%", { percent: Math.round(dimension.score / Math.max(1, dimension.max_points) * 100) })}</p>
      {dimension.evidence_level && <div className="mt-4"><StatusChip tone={dimension.evidence_level === "verified" ? "success" : dimension.evidence_level === "supported" ? "info" : "neutral"}>{t(dimension.evidence_level === "verified" ? "已验证" : dimension.evidence_level === "supported" ? "佐证可信" : "仅自述")}</StatusChip></div>}
      <p className="mt-4 whitespace-pre-wrap text-body-sm leading-6 text-on-surface">{dimension.reason || t("暂无评分说明")}</p>
      {!!dimension.highlights?.length && <div className="mt-4 space-y-2 border-t border-outline-variant pt-4">
        {dimension.highlights.map((item, index) => <p key={index} className="flex gap-2 text-body-sm text-on-surface"><Icon name="check_circle" size={16} className="mt-0.5 shrink-0 text-success" />{item}</p>)}
      </div>}
      {!!dimension.anomalies?.length && <div className="mt-4 space-y-2 border-t border-outline-variant pt-4">
        {dimension.anomalies.map((item, index) => <p key={index} className="flex gap-2 text-body-sm text-on-surface"><Icon name="warning" size={16} className="mt-0.5 shrink-0 text-warning" />{item}</p>)}
      </div>}
    </div>
  );
}
