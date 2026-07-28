import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";
import Icon from "./Icon";

type Variant = "filled" | "tonal" | "outlined" | "text";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  icon?: string;
  children?: ReactNode;
}

const variantClass: Record<Variant, string> = {
  filled: "bg-primary text-on-primary",
  tonal: "bg-secondary-container text-on-secondary-container",
  outlined: "border border-outline text-primary bg-transparent",
  text: "text-primary bg-transparent",
};

/** MD3 Button：full 圆角 + state layer */
export default function Button({ variant = "filled", icon, children, className, ...rest }: ButtonProps) {
  return (
    <button
      className={cn(
        "state-layer inline-flex items-center justify-center gap-2 h-10 px-5 rounded-full",
        "text-sm font-medium cursor-pointer select-none transition-colors duration-150",
        "disabled:opacity-40 disabled:pointer-events-none",
        variantClass[variant],
        className
      )}
      {...rest}
    >
      {icon && <Icon name={icon} size={18} />}
      {children}
    </button>
  );
}

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: string;
  variant?: "standard" | "filled" | "tonal" | "outlined";
  size?: number;
}

const iconVariantClass: Record<NonNullable<IconButtonProps["variant"]>, string> = {
  standard: "text-on-surface-variant bg-transparent",
  filled: "bg-primary text-on-primary",
  tonal: "bg-secondary-container text-on-secondary-container",
  outlined: "border border-outline-variant text-on-surface-variant bg-transparent",
};

/** MD3 Icon Button：40px 圆形 */
export function IconButton({ icon, variant = "standard", size = 20, className, ...rest }: IconButtonProps) {
  return (
    <button
      className={cn(
        "state-layer inline-flex items-center justify-center w-10 h-10 rounded-full",
        "cursor-pointer select-none transition-colors duration-150 disabled:opacity-40 disabled:pointer-events-none",
        iconVariantClass[variant],
        className
      )}
      {...rest}
    >
      <Icon name={icon} size={size} />
    </button>
  );
}
