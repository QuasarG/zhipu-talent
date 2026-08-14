import { NavLink } from "react-router-dom";
import { cn } from "@/lib/cn";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import Icon from "@/components/ui/Icon";
import LangToggle from "@/components/LangToggle";
import logoUrl from "@/assets/zhipu-logo.svg";

const navItems = [
  { to: "/", icon: "forum", label: "人才问答" },
  { to: "/talent-pool", icon: "groups", label: "人才库" },
  { to: "/resume-evaluate", icon: "description", label: "简历评估" },
  { to: "/scholarship", icon: "workspace_premium", label: "奖学金" },
  { to: "/settings", icon: "settings", label: "设置" },
];

/** MD3 Navigation Rail：80px 全高，active = pill 指示器 */
export default function NavRail({ username }: { username?: string }) {
  const { t } = useI18n();
  return (
    <nav data-tour="nav" className="sticky top-0 h-screen w-24 shrink-0 flex flex-col items-center py-5 bg-surface z-40">
      {/* Logo */}
      <img src={logoUrl} alt={t("智谱")} className="h-5 mb-9 select-none" draggable={false} />

      {/* 导航项 */}
      <ul className="flex flex-col gap-3 flex-1 w-full items-center">
        {navItems.map(({ to, icon, label }) => {
          const tourKey = to === "/" ? "nav-chat" : to === "/resume-evaluate" ? "nav-resume" : to === "/talent-pool" ? "nav-pool" : to === "/scholarship" ? "nav-scholarship" : "nav-settings";
          return (
          <li key={to} className="w-full flex justify-center">
            <NavLink
              to={to}
              end={to === "/"}
              data-tour={tourKey}
              className="flex flex-col items-center gap-1.5 w-20 no-underline group"
            >
              {({ isActive }) => (
                <>
                  <span
                    className={cn(
                      "state-layer flex items-center justify-center w-16 h-9 rounded-full transition-colors duration-150",
                      isActive
                        ? "bg-secondary-container text-on-secondary-container"
                        : "text-on-surface-variant group-hover:text-on-surface"
                    )}
                  >
                    <Icon name={icon} size={24} fill={isActive} />
                  </span>
                  <span
                    className={cn(
                      "text-label nav-rail-label",
                      isActive ? "text-on-surface font-semibold" : "text-on-surface-variant"
                    )}
                  >
                    {t(label)}
                  </span>
                </>
              )}
            </NavLink>
          </li>
          );
        })}
      </ul>

      {/* 用户 + 语言 + 登出 */}
      <div className="mt-auto flex flex-col items-center gap-3">
        <LangToggle className="w-20 h-9 rounded-full" />
        <button
          onClick={() => api.auth.logout().then(() => window.location.reload())}
          className="state-layer w-10 h-10 rounded-full text-on-surface-variant flex items-center justify-center cursor-pointer"
          title={t("退出登录")}
        >
          <Icon name="logout" size={20} />
        </button>
        <div className="w-9 h-9 rounded-full bg-primary-container text-on-primary-container flex items-center justify-center text-xs font-semibold relative" title={username}>
          {(username || "?").slice(0, 1)}
          <span className="absolute bottom-0 right-0 w-2.5 h-2.5 rounded-full bg-success border-2 border-surface" />
        </div>
      </div>
    </nav>
  );
}
