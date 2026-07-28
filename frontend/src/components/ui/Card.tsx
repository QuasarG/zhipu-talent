import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: "filled" | "outlined" | "elevated";
  children: ReactNode;
}

const variantClass = {
  filled: "md3-card",
  outlined: "md3-card-outlined",
  elevated: "md3-card-elevated",
} as const;

/** MD3 Card：tonal surface 表达层级 */
export default function Card({ variant = "filled", children, className, ...rest }: CardProps) {
  return (
    <div className={cn(variantClass[variant], className)} {...rest}>
      {children}
    </div>
  );
}
