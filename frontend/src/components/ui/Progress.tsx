import { cn } from "@/lib/cn";

interface ProgressProps {
  value: number; // 0-100
  color?: string; // token 色值或 tailwind bg 类对应的颜色
  className?: string;
  barClassName?: string;
}

/** MD3 Linear Progress：surface-highest 轨道 */
export default function Progress({ value, color, className, barClassName }: ProgressProps) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className={cn("h-1.5 w-full rounded-full bg-surface-highest overflow-hidden", className)}>
      <div
        className={cn("h-full rounded-full transition-[width] duration-300", !color && "bg-primary", barClassName)}
        style={{ width: `${pct}%`, ...(color ? { backgroundColor: color } : {}) }}
      />
    </div>
  );
}
