import { cn } from "@/lib/cn";

interface IconProps {
  name: string;
  fill?: boolean;
  size?: number;
  className?: string;
}

/** Material Symbols Outlined 图标 */
export default function Icon({ name, fill = false, size = 20, className }: IconProps) {
  return (
    <span
      aria-hidden="true"
      className={cn("md-icon", fill && "md-icon-fill", className)}
      style={{ fontSize: size }}
    >
      {name}
    </span>
  );
}
