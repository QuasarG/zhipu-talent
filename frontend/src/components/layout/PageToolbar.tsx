import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface PageToolbarProps {
  title: string;
  subtitle?: string;
  center?: ReactNode;
  right?: ReactNode;
}

export default function PageToolbar({ title, subtitle, center, right }: PageToolbarProps) {
  return (
    <header className="glass flex items-center gap-4 px-5 py-3 rounded-[14px] mb-4 min-h-[56px]">
      <div className="shrink-0">
        <h1 className="text-lg font-semibold leading-tight">{title}</h1>
        {subtitle && <p className="text-xs text-ink-secondary mt-0.5">{subtitle}</p>}
      </div>
      {center && <div className="flex-1 flex justify-center">{center}</div>}
      {right && <div className="flex items-center gap-2 shrink-0">{right}</div>}
    </header>
  );
}
