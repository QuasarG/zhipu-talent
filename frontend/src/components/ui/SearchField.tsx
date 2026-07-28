import type { InputHTMLAttributes } from "react";
import { cn } from "@/lib/cn";
import Icon from "./Icon";

interface SearchFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  className?: string;
}

/** MD3 Search Bar：full 圆角 tonal 容器 */
export default function SearchField({ className, ...rest }: SearchFieldProps) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 h-10 px-4 rounded-full bg-surface-high text-on-surface-variant",
        "focus-within:outline-2 focus-within:outline-primary",
        className
      )}
    >
      <Icon name="search" size={18} className="shrink-0" />
      <input
        type="search"
        className="flex-1 min-w-0 bg-transparent border-none outline-none text-sm text-on-surface placeholder:text-on-surface-variant"
        {...rest}
      />
    </div>
  );
}
