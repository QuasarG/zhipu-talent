import { useState } from "react";
import { cn } from "@/lib/cn";

interface ScoreRingProps {
  /** 当前分值 */
  value: number;
  /** 满分（决定环的比例与颜色段） */
  max: number;
  /** 主标题（中文） */
  label: string;
  /** 副标题（英文，可选） */
  labelEn?: string;
  size?: number;
  /** 环粗（px） */
  stroke?: number;
  className?: string;
}

/** 分数占比 → 颜色 token：≥80% 优秀绿，≥60% 良好主色，≥40% 中性，其余警示 */
function toneClass(ratio: number) {
  if (ratio >= 0.8) return { stroke: "var(--color-success)", text: "text-success" };
  if (ratio >= 0.6) return { stroke: "var(--color-primary)", text: "text-primary" };
  if (ratio >= 0.4) return { stroke: "var(--color-tertiary)", text: "text-tertiary" };
  return { stroke: "var(--color-warning)", text: "text-warning" };
}

/** SVG 环形分数计：总分大环 / 维度小环共用 */
export default function ScoreRing({ value, max, label, labelEn, size = 64, stroke = 6, className }: ScoreRingProps) {
  const [hover, setHover] = useState(false);
  const ratio = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
  const tone = toneClass(ratio);
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  // 从顶部起笔
  const dash = c * ratio;
  return (
    <div
      className={cn("flex shrink-0 flex-col items-center gap-1 select-none", className)}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <circle cx={size / 2} cy={size / 2} r={r} fill="none"
            stroke="var(--color-surface-high)" strokeWidth={stroke} />
          <circle cx={size / 2} cy={size / 2} r={r} fill="none"
            stroke={tone.stroke} strokeWidth={stroke} strokeLinecap="round"
            strokeDasharray={`${dash} ${c - dash}`}
            style={{ transition: "stroke-dasharray 400ms var(--ease-emphasized)" }} />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={cn("font-mono font-semibold tabular-nums leading-none", tone.text)}
            style={{ fontSize: size >= 100 ? 22 : size >= 80 ? 15 : 12 }}>
            {Number.isInteger(value) ? value : value.toFixed(1)}
          </span>
          {size >= 80 && (
            <span className="mt-0.5 text-[10px] leading-none text-on-surface-variant">/{max}</span>
          )}
        </div>
      </div>
      <div className="max-w-full text-center leading-tight">
        <div className={cn("truncate", hover ? "text-on-surface" : "text-on-surface-variant")}
          style={{ fontSize: size >= 100 ? 13 : 11 }} title={label}>
          {label}
        </div>
        {labelEn && size >= 80 && (
          <div className="truncate text-[10px] text-on-surface-variant" title={labelEn}>{labelEn}</div>
        )}
      </div>
    </div>
  );
}
