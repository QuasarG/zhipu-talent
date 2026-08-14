import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import chatEn from "@/i18n/en/chat";
import grillEn from "@/i18n/en/grill";
import poolEn from "@/i18n/en/pool";
import resumeEn from "@/i18n/en/resume";
import scholarshipEn from "@/i18n/en/scholarship";
import settingsEn from "@/i18n/en/settings";
import miscEn from "@/i18n/en/misc";

export type Lang = "zh" | "en";

// 中文文案即 key：zh 直接回显 key 本身，en 查字典，查不到回退中文
const enDict: Record<string, string> = Object.assign(
  {},
  chatEn,
  grillEn,
  poolEn,
  resumeEn,
  scholarshipEn,
  settingsEn,
  miscEn
);

const STORAGE_KEY = "talent-radar-lang";

function readInitialLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "zh" || saved === "en") return saved;
  } catch {
    // localStorage 不可用时静默回退默认语言
  }
  return "zh";
}

type Params = Record<string, string | number>;

function interpolate(template: string, params?: Params): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (m, k: string) => (k in params ? String(params[k]) : m));
}

interface I18nValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: (key: string, params?: Params) => string;
}

const I18nContext = createContext<I18nValue | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(readInitialLang);

  useEffect(() => {
    document.documentElement.lang = lang === "en" ? "en" : "zh-CN";
    document.title = lang === "en" ? "AGI Talent Radar" : "智谱人才雷达";
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // 忽略写入失败
    }
  }, []);

  const t = useCallback(
    (key: string, params?: Params) => interpolate(lang === "en" ? enDict[key] ?? key : key, params),
    [lang]
  );

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n 必须在 I18nProvider 内使用");
  return ctx;
}
