import type { ReactNode } from "react";

interface PageToolbarProps {
  title: string;
  subtitle?: string;
  center?: ReactNode;
  right?: ReactNode;
}

/** MD3 Top App Bar */
export default function PageToolbar({ title, subtitle, center, right }: PageToolbarProps) {
  return (
    <header className="flex items-center gap-6 px-2 py-3 mb-4 min-h-16">
      <div className="shrink-0">
        <h1 className="text-headline leading-tight">{title}</h1>
        {subtitle && <p className="text-body-sm text-on-surface-variant mt-0.5">{subtitle}</p>}
      </div>
      {center && <div className="flex-1 flex justify-center">{center}</div>}
      {right && <div className="flex items-center gap-2 shrink-0 ml-auto">{right}</div>}
    </header>
  );
}
