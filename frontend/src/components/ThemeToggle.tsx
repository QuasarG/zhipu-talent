import { useI18n } from "@/lib/i18n";
import { useTheme, type ThemeMode } from "@/lib/theme";
import Icon from "@/components/ui/Icon";
import { cn } from "@/lib/cn";

const CYCLE: ThemeMode[] = ["light", "dark", "system"];
const ICON: Record<ThemeMode, string> = { light: "light_mode", dark: "dark_mode", system: "routine" };

/** 主题快捷按钮：点击循环 浅色 → 深色 → 跟随系统 */
export default function ThemeToggle({ className }: { className?: string }) {
  const { t } = useI18n();
  const { mode, setMode } = useTheme();
  const next = CYCLE[(CYCLE.indexOf(mode) + 1) % CYCLE.length];
  const label: Record<ThemeMode, string> = {
    light: t("浅色"),
    dark: t("深色"),
    system: t("跟随系统"),
  };
  return (
    <button
      onClick={() => setMode(next)}
      className={cn(
        "state-layer w-10 h-10 rounded-full text-on-surface-variant hover:text-on-surface",
        "flex items-center justify-center cursor-pointer transition-colors",
        className
      )}
      title={t("当前：{mode}，点击切换", { mode: label[mode] })}
      aria-label={t("切换主题")}
    >
      <Icon name={ICON[mode]} size={20} />
    </button>
  );
}
