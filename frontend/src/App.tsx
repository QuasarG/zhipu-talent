import { BrowserRouter, Routes, Route, Navigate, useSearchParams } from "react-router-dom";
import { useState, useEffect } from "react";
import { api } from "./lib/api";
import { useI18n } from "./lib/i18n";
import NavRail from "./components/layout/NavRail";
import LoadingIndicator from "./components/ui/LoadingIndicator";
import Login from "./pages/Login";
import TalentChat from "./pages/TalentChat";
import TalentEvaluation from "./pages/TalentEvaluation";
import TalentPool from "./pages/TalentPool";
import TalentProfile from "./pages/TalentProfile";
import JdPool from "./pages/JdPool";
import Scholarship from "./pages/Scholarship";
import Settings from "./pages/Settings";
import SharedProfile from "./pages/SharedProfile";
import OnboardingTour from "./components/OnboardingTour";

/** 旧入口迁移兼容：保留 ?focus= 跳转参数，统一回到面试准入子界面（能力评估入口暂时移除） */
function EvaluationRedirect({ to }: { to: string }) {
  const [params] = useSearchParams();
  const focus = params.get("focus");
  return <Navigate to={focus ? `${to}?focus=${encodeURIComponent(focus)}` : to} replace />;
}

function App() {
  const [currentUser, setCurrentUser] = useState<{ id: string; username: string; display_name: string } | null | undefined>(undefined);
  const { t } = useI18n();

  useEffect(() => {
    api.auth.status().then((d) => setCurrentUser(d.user));
  }, []);

  if (currentUser === undefined) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <LoadingIndicator size={32} label={t("加载中…")} />
      </div>
    );
  }

  // 只读分享页：凭随机 token 自证，不要求登录，也不进主应用布局
  if (window.location.pathname.startsWith("/share/")) {
    return <SharedProfile />;
  }

  if (currentUser === null) {
    return <Login onLogin={() => api.auth.status().then((d) => setCurrentUser(d.user))} />;
  }

  return (
    <BrowserRouter>
      <div className="flex min-h-screen">
        <NavRail username={currentUser.display_name || currentUser.username} />
        <main className="flex-1 min-w-0 px-6 pb-6">
          <Routes>
            <Route path="/" element={<TalentPool />} />
            {/* 统一"人才评估"外壳：当前只承载面试准入 */}
            <Route path="/talent-evaluation/*" element={<TalentEvaluation />} />
            {/* 能力评估入口暂时移除：旧地址与迁移兼容入口统一回到面试准入 */}
            <Route path="/talent-evaluation/capability" element={<EvaluationRedirect to="/talent-evaluation/admission" />} />
            <Route path="/resume-evaluate" element={<EvaluationRedirect to="/talent-evaluation/admission" />} />
            <Route path="/interview-admission" element={<Navigate to="/talent-evaluation/admission" replace />} />
            <Route path="/chat" element={<TalentChat />} />
            <Route path="/knowledge" element={<Navigate to="/chat" replace />} />
            <Route path="/talent-pool" element={<Navigate to="/" replace />} />
            <Route path="/talent-pool/:personId" element={<TalentProfile />} />
            <Route path="/jd-pool" element={<JdPool />} />
            <Route path="/scholarship" element={<Scholarship />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
      <OnboardingTour />
    </BrowserRouter>
  );
}

export default App;
