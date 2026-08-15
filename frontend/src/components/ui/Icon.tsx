import { Icon as IconifyIcon, addCollection } from "@iconify/react";
import subset from "@/assets/tabler-subset.json";
import nameMap from "@/assets/icon-name-map.json";

// 离线加载 Tabler Icons 子集（2px 描边线条风，~26KB），不依赖网络
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
      icon={`tabler:${iconifyName}`}
      width={size}
      height={size}
      className={className}
      style={fill ? { fontVariationSettings: '"FILL" 1' } : undefined}
    />
  );
}
