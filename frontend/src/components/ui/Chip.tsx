import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";
import Icon from "./Icon";

interface ChipProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  selected?: boolean;
  icon?: string;
  children: ReactNode;
}

/** MD3 Filter Chip：选中 = secondary-container */
export default function Chip({ selected = false, icon, children, className, ...rest }: ChipProps) {
  return (
    <button
      className={cn(
        "state-layer inline-flex items-center gap-1.5 h-8 px-3.5 rounded-full text-[13px] font-medium",
        "cursor-pointer select-none transition-colors duration-150",
        selected
          ? "bg-secondary-container text-on-secondary-container"
          : "border border-outline-variant text-on-surface-variant bg-transparent",
        className
      )}
      {...rest}
    >
      {selected && <Icon name="check" size={16} />}
      {!selected && icon && <Icon name={icon} size={16} />}
      {children}
    </button>
  );
}

type Tone = "success" | "warning" | "error" | "info" | "neutral" | "primary";

const toneClass: Record<Tone, string> = {
  success: "bg-success-container text-success",
  warning: "bg-warning-container text-warning",
  error: "bg-error-container text-error",
  info: "bg-tertiary-container text-tertiary",
  primary: "bg-primary-container text-on-primary-container",
  neutral: "bg-surface-high text-on-surface-variant",
};

const dotToneClass: Record<Tone, string> = {
  success: "bg-success",
  warning: "bg-warning",
  error: "bg-error",
  info: "bg-tertiary",
  primary: "bg-primary",
  neutral: "bg-outline",
};

interface StatusChipProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
  /** dot（默认）= 中性底+彩色小圆点，安静；filled = 彩色容器，只给真告警 */
  variant?: "dot" | "filled";
  /** sm（默认）= 列表内嵌；md = 工具栏，与 Button/IconButton 等高 */
  size?: "sm" | "md";
  icon?: string;
  children: ReactNode;
}

/** 状态徽章：默认圆点式保持界面安静，filled 仅用于需要强提醒的状态 */
export function StatusChip({ tone = "neutral", variant = "dot", size = "sm", icon, children, className, ...rest }: StatusChipProps) {
  const sizeClass = size === "md" ? "h-10 px-4 text-sm gap-2" : "h-6 px-2.5 text-xs gap-1.5";
  const dotClass = size === "md" ? "w-2 h-2" : "w-1.5 h-1.5";
  const iconSize = size === "md" ? 18 : 14;
  if (variant === "filled") {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1 rounded-full font-medium whitespace-nowrap",
          sizeClass,
          toneClass[tone],
          className
        )}
        {...rest}
      >
        {icon && <Icon name={icon} size={iconSize} />}
        {children}
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full font-medium whitespace-nowrap bg-surface-high text-on-surface-variant",
        sizeClass,
        className
      )}
      {...rest}
    >
      <span className={cn("rounded-full shrink-0", dotClass, dotToneClass[tone])} />
      {icon && <Icon name={icon} size={iconSize} />}
      {children}
    </span>
  );
}
