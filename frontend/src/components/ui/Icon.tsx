import { Icon as IconifyIcon, addCollection } from "@iconify/react";
import subset from "@/assets/material-symbols-subset.json";
import nameMap from "@/assets/icon-name-map.json";

// 离线加载 69 个 Material Symbols 图标子集（~20KB），不依赖网络
addCollection(subset as never);

const MAP = nameMap as Record<string, string>;

interface IconProps {
  name: string;
  fill?: boolean;
  size?: number;
  className?: string;
}

/** Material Symbols 图标（Iconify 离线子集，渲染即 SVG，不闪字符） */
export default function Icon({ name, fill = false, size = 20, className }: IconProps) {
  const iconifyName = MAP[name] || name.replace(/_/g, "-");
  return (
    <IconifyIcon
      icon={`material-symbols:${iconifyName}`}
      width={size}
      height={size}
      className={className}
      style={fill ? { fontVariationSettings: '"FILL" 1' } : undefined}
    />
  );
}
