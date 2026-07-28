import { cn } from "@/lib/cn";

interface TabItem<T extends string> {
  value: T;
  label: string;
  badge?: number | string;
}

interface TabsProps<T extends string> {
  items: TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}

/** MD3 Primary Tabs：底部指示条 */
export default function Tabs<T extends string>({ items, value, onChange, className }: TabsProps<T>) {
  return (
    <div className={cn("flex border-b border-outline-variant", className)} role="tablist">
      {items.map((item) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.value)}
            className={cn(
              "state-layer relative flex-1 h-11 px-3 text-sm font-medium cursor-pointer transition-colors duration-150",
              active ? "text-primary" : "text-on-surface-variant"
            )}
          >
            <span className="inline-flex items-center gap-1.5">
              {item.label}
              {item.badge !== undefined && (
                <span className="inline-flex items-center justify-center min-w-5 h-5 px-1 rounded-full bg-surface-highest text-on-surface-variant text-xs font-medium">
                  {item.badge}
                </span>
              )}
            </span>
            {active && (
              <span className="absolute bottom-0 left-3 right-3 h-[3px] rounded-t-full bg-primary" />
            )}
          </button>
        );
      })}
    </div>
  );
}
