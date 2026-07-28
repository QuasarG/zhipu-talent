import { NavLink } from "react-router-dom";
import { FileText, MessageCircle, Users, CheckSquare, Settings, LogOut } from "lucide-react";
import { cn } from "@/lib/cn";
import { api } from "@/lib/api";

const navItems = [
  { to: "/", icon: FileText, label: "简历评估" },
  { to: "/knowledge", icon: MessageCircle, label: "人才知识" },
  { to: "/talent-pool", icon: Users, label: "人才库" },
  { to: "/review", icon: CheckSquare, label: "待核验" },
  { to: "/settings", icon: Settings, label: "设置" },
];

export default function NavRail() {
  return (
    <nav className="glass fixed top-5 left-5 bottom-5 w-[72px] rounded-[20px] flex flex-col items-center py-4 z-[100] contain-layout contain-paint">
      {/* Logo */}
      <div className="w-10 h-10 rounded-[14px] bg-gradient-to-br from-teal to-teal-light text-white flex items-center justify-center font-bold text-base mb-6 shadow-sm">
        Z
      </div>

      {/* 导航项 */}
      <ul className="flex flex-col gap-2 flex-1 w-full items-center">
        {navItems.map(({ to, icon: Icon, label }) => (
          <li key={to}>
            <NavLink
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex flex-col items-center gap-[3px] px-1 py-2 rounded-[10px] w-[56px] transition-all duration-150",
                  "text-ink-secondary hover:text-ink hover:bg-white/35 no-underline",
                  isActive && "text-teal bg-teal-soft"
                )
              }
            >
              <Icon size={22} strokeWidth={1.8} />
              <span className="text-[10px] leading-[1.2]">{label}</span>
            </NavLink>
          </li>
        ))}
      </ul>

      {/* 用户 + 登出 */}
      <div className="mt-auto flex flex-col items-center gap-2">
        <button
          onClick={() => api.auth.logout().then(() => window.location.reload())}
          className="w-9 h-9 rounded-full bg-surface-mist text-ink flex items-center justify-center hover:bg-white/40 transition-colors"
          title="退出登录"
        >
          <LogOut size={16} strokeWidth={1.8} />
        </button>
        <div className="w-9 h-9 rounded-full bg-surface-mist text-ink flex items-center justify-center text-xs font-semibold relative">
          HR
          <span className="absolute bottom-0.5 right-0.5 w-2.5 h-2.5 rounded-full bg-teal-light border-2 border-surface-cool" />
        </div>
      </div>
    </nav>
  );
}
