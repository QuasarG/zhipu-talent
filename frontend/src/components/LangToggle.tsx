import { useI18n } from "@/lib/i18n";
import Icon from "@/components/ui/Icon";
import { cn } from "@/lib/cn";

/** 中英文切换按钮：显示切换目标语言，点击切换 */
export default function LangToggle({ className }: { className?: string }) {
  const { lang, setLang } = useI18n();
  return (
    <button
      onClick={() => setLang(lang === "zh" ? "en" : "zh")}
      className={cn(
        "state-layer inline-flex items-center justify-center gap-1.5 rounded-full",
        "text-on-surface-variant hover:text-on-surface cursor-pointer",
        "text-label select-none transition-colors",
        className
      )}
      title={lang === "zh" ? "Switch to English" : "切换到中文"}
    >
      <Icon name="translate" size={18} />
      <span className="font-semibold">{lang === "zh" ? "EN" : "中文"}</span>
    </button>
  );
}
