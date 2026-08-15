import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "@/lib/api";
import type { PersonDetail } from "@/lib/types";
import Icon from "@/components/ui/Icon";
import LangToggle from "@/components/LangToggle";
import ThemeToggle from "@/components/ThemeToggle";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import TalentDetail from "@/features/pool/TalentDetail";
import { useI18n } from "@/lib/i18n";
import { useTheme } from "@/lib/theme";
import logoUrl from "@/assets/zhipu-logo.svg";
import logoWhiteUrl from "@/assets/zhipu-logo-white.svg";
import logoEnUrl from "@/assets/zai-logo-en.svg";
import logoEnWhiteUrl from "@/assets/zai-logo-en-white.svg";

/**
 * 只读分享页：凭随机 token 查看单个候选人的完整档案与评估记录。
 * 与主应用完全隔离——无侧栏/无导航/无任何他人数据；保留 logo、三主题、中英切换。
 */
export default function SharedProfile() {
  const { token = "" } = useParams();
  const [person, setPerson] = useState<PersonDetail | null>(null);
  const [error, setError] = useState("");
  const { t, lang } = useI18n();
  const { resolved } = useTheme();

  useEffect(() => {
    api.share
      .get(token)
      .then(setPerson)
      .catch((e) => setError(e instanceof Error ? e.message : t("链接无效或已被撤销")));
  }, [token, t]);

  const logoSrc =
    lang === "en"
      ? resolved === "dark"
        ? logoEnWhiteUrl
        : logoEnUrl
      : resolved === "dark"
        ? logoWhiteUrl
        : logoUrl;

  return (
    <div className="min-h-screen bg-surface">
      {/* 顶栏：logo + 主题/语言切换（分享页唯一的全局元素） */}
      <header className="flex items-center justify-between px-6 h-14 border-b border-outline-variant bg-surface-lowest">
        <div className="flex items-center gap-3">
          <img src={logoSrc} alt="Zhipu" className="h-5 select-none" draggable={false} />
          <span className="text-label text-on-surface-variant">{t("人才档案 · 只读分享")}</span>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <LangToggle className="h-9 px-3 rounded-md border border-outline-variant" />
        </div>
      </header>

      <main className="max-w-[860px] mx-auto p-6">
        {error ? (
          <div className="flex flex-col items-center justify-center py-24 gap-3 text-center">
            <Icon name="lock" size={36} className="text-on-surface-variant" />
            <p className="text-title-lg text-on-surface">{t("无法打开此分享链接")}</p>
            <p className="text-body-sm text-on-surface-variant">{error}</p>
          </div>
        ) : !person ? (
          <div className="flex items-center justify-center py-24">
            <LoadingIndicator size={32} label={t("加载中…")} />
          </div>
        ) : (
          <TalentDetail person={person} personId={person.id} onUpdated={async () => {}} readOnly />
        )}
      </main>
    </div>
  );
}
