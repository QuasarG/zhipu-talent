import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface GlassPanelProps {
  children: ReactNode;
  className?: string;
  variant?: "default" | "strong" | "dark";
}

export default function GlassPanel({ children, className, variant = "default" }: GlassPanelProps) {
  const variantClass =
    variant === "strong" ? "glass-strong" : variant === "dark" ? "glass-dark" : "glass";
  return <div className={cn(variantClass, "rounded-xl", className)}>{children}</div>;
}
