import { cn } from "@/lib/cn";

interface LoadingIndicatorProps {
  /** 圆环直径（px）；MD3 默认 24，紧凑场景可设 16/20 */
  size?: number;
  /** 描边粗细（px）；默认按 size 比例，或显式指定 */
  strokeWidth?: number;
  /** 颜色 token 类名，如 text-primary / text-on-surface-variant */
  color?: string;
  className?: string;
  /** 带文字标签（如「评估中」），放在指示器右侧 */
  label?: string;
}

/**
 * MD3 Loading Indicator：单色圆环 + 双层动效。
 *
 * 实现 MD3 规范要点：
 * - 双段动效叠加：基础旋转（线性匀速 1560ms）+ 脉冲缩放（emphasized 1330ms）
 * - 3/4 圆弧（缺口），非完整圆
 * - 单色，默认 primary
 *
 * 用于替换所有 progress_activity + animate-spin 临时方案。
 */
export default function LoadingIndicator({
  size = 24,
  strokeWidth,
  color = "text-primary",
  className,
  label,
}: LoadingIndicatorProps) {
  // 描边默认按直径比例：24→3, 16→2, 32→4
  const sw = strokeWidth ?? Math.max(2, Math.round(size / 8));
  const radius = (size - sw) / 2;
  const circumference = 2 * Math.PI * radius;
  // 3/4 圆弧缺口
  const dashLength = circumference * 0.75;

  return (
    <span
      className={cn("inline-flex items-center gap-2", color, className)}
      role="status"
      aria-live="polite"
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className="md3-loading-spinner"
        style={{ animation: "md3-loading-rotate 1560ms linear infinite" }}
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="currentColor"
          strokeWidth={sw}
          strokeLinecap="round"
          strokeDasharray={`${dashLength} ${circumference}`}
          className="md3-loading-arc"
          style={{ animation: "md3-loading-pulse 1330ms cubic-bezier(0.2, 0, 0, 1) infinite" }}
        />
      </svg>
      {label && <span className="text-body-sm">{label}</span>}
    </span>
  );
}
