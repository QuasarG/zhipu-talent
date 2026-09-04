import { NavLink, useLocation } from "react-router-dom";
import { cn } from "@/lib/cn";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useTheme } from "@/lib/theme";
import Icon from "@/components/ui/Icon";
import LangToggle from "@/components/LangToggle";
import ThemeToggle from "@/components/ThemeToggle";
import logoUrl from "@/assets/zhipu-logo.svg";
import logoWhiteUrl from "@/assets/zhipu-logo-white.svg";
import logoEnUrl from "@/assets/zai-logo-en.svg";
import logoEnWhiteUrl from "@/assets/zai-logo-en-white.svg";

interface NavItem {
  to: string;
  icon: string;
  label: string;
  /** 高亮匹配前缀（用于一个入口覆盖多个子路由，如人才评估的 admission/capability） */
  matchPrefix?: string;
}

const navItems: NavItem[] = [
  { to: "/", icon: "groups", label: "人才库" },
  { to: "/talent-evaluation/admission", icon: "fact_check", label: "人才评估", matchPrefix: "/talent-evaluation" },
  { to: "/chat", icon: "forum", label: "人才问答" },
  { to: "/jd-pool", icon: "work", label: "JD 池" },
  { to: "/scholarship", icon: "workspace_premium", label: "奖学金" },
  { to: "/settings", icon: "settings", label: "设置" },
];

const FEEDBACK_URL = "https://zhipu-ai.feishu.cn/share/base/form/shrcnBnsxfWPAOZW1yP12PA9RGg";

/** MD3 Navigation Rail：80px 全高，active = pill 指示器 */
export default function NavRail({ username }: { username?: string }) {
  const { t, lang } = useI18n();
  const { resolved } = useTheme();
  const location = useLocation();
  const logoSrc =
    lang === "en"
      ? resolved === "dark"
        ? logoEnWhiteUrl
        : logoEnUrl
      : resolved === "dark"
        ? logoWhiteUrl
        : logoUrl;
  return (
    <nav data-tour="nav" className="sticky top-0 h-screen w-24 shrink-0 flex flex-col items-center py-5 bg-surface z-40">
      {/* Logo：按语言（中/英）× 主题（浅/深）四象限选择 */}
      <img
        src={logoSrc}
        alt={t("智谱")}
        className="h-5 mb-9 select-none"
        draggable={false}
      />

      {/* 导航项 */}
      <ul className="flex flex-col gap-3 flex-1 w-full items-center">
        {navItems.map(({ to, icon, label, matchPrefix }) => {
          const tourKey = to === "/" ? "nav-pool" : to === "/talent-evaluation/admission" ? "nav-talent-evaluation" : to === "/chat" ? "nav-chat" : to === "/scholarship" ? "nav-scholarship" : "nav-settings";
          return (
          <li key={to} className="w-full flex justify-center">
            <NavLink
              to={to}
              end={to === "/"}
              data-tour={tourKey}
              className="flex flex-col items-center gap-1.5 w-20 no-underline group"
            >
              {({ isActive }) => {
                const active = isActive || (matchPrefix ? location.pathname.startsWith(matchPrefix) : false);
                return (
                <>
                  <span
                    className={cn(
                      "state-layer flex items-center justify-center w-16 h-9 rounded-full transition-colors duration-150",
                      active
                        ? "bg-secondary-container text-on-secondary-container"
                        : "text-on-surface-variant group-hover:text-on-surface"
                    )}
                  >
                    <Icon name={icon} size={24} fill={active} />
                  </span>
                  <span
                    className={cn(
                      "text-label nav-rail-label",
                      active ? "text-on-surface font-semibold" : "text-on-surface-variant"
                    )}
                  >
                    {t(label)}
                  </span>
                </>
                );
              }}
            </NavLink>
          </li>
          );
        })}
      </ul>

      {/* 用户 + 语言 + 主题 + 登出 */}
      <div className="mt-auto flex flex-col items-center gap-3">
        <a
          href={FEEDBACK_URL}
          target="_blank"
          rel="noreferrer"
          className="group flex w-20 flex-col items-center gap-1.5 no-underline"
          title={t("反馈建议")}
        >
          <span className="state-layer flex h-9 w-16 items-center justify-center rounded-full text-on-surface-variant transition-colors duration-150 group-hover:bg-surface-high group-hover:text-on-surface">
            <Icon name="lightbulb" size={22} />
          </span>
          <span className="nav-rail-label text-label text-on-surface-variant group-hover:text-on-surface">
            {t("反馈建议")}
          </span>
        </a>
        <LangToggle className="w-20 h-9 rounded-full" />
        <ThemeToggle />
        <button
          onClick={() => api.auth.logout().then(() => window.location.reload())}
          className="state-layer w-10 h-10 rounded-full text-on-surface-variant flex items-center justify-center cursor-pointer"
          title={t("退出登录")}
        >
          <Icon name="logout" size={20} />
        </button>
        <div className="initial-avatar w-9 h-9 rounded-full bg-primary-container text-on-primary-container flex items-center justify-center text-xs font-semibold relative" title={username}>
          {(username || "?").slice(0, 1)}
          <span className="absolute bottom-0 right-0 w-2.5 h-2.5 rounded-full bg-success border-2 border-surface" />
        </div>
      </div>
    </nav>
  );
}
