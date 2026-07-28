import { cn } from "@/lib/cn";
import Icon from "./Icon";

interface Option<T extends string> {
  value: T;
  label: string;
  icon?: string;
}

interface SegmentedButtonsProps<T extends string> {
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}

/** MD3 Segmented Button（单选） */
export default function SegmentedButtons<T extends string>({
  options,
  value,
  onChange,
  className,
}: SegmentedButtonsProps<T>) {
  return (
    <div className={cn("inline-flex rounded-full border border-outline-variant overflow-hidden", className)}>
      {options.map((opt, i) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            className={cn(
              "state-layer inline-flex items-center justify-center gap-1.5 h-9 px-4 text-[13px] font-medium cursor-pointer whitespace-nowrap",
              "transition-colors duration-150",
              i > 0 && "border-l border-outline-variant",
              active ? "bg-secondary-container text-on-secondary-container" : "text-on-surface-variant bg-transparent"
            )}
          >
            {active ? <Icon name="check" size={16} /> : opt.icon && <Icon name={opt.icon} size={16} />}
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
