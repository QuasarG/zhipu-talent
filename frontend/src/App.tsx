import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useState, useEffect } from "react";
import { api } from "./lib/api";
import NavRail from "./components/layout/NavRail";
import LoadingIndicator from "./components/ui/LoadingIndicator";
import Login from "./pages/Login";
import TalentChat from "./pages/TalentChat";
import ResumeEvaluate from "./pages/ResumeEvaluate";
import TalentPool from "./pages/TalentPool";
import TalentProfile from "./pages/TalentProfile";
import Settings from "./pages/Settings";

function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    api.auth.status().then((d) => setAuthed(d.authenticated));
  }, []);

  if (authed === null) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <LoadingIndicator size={32} label="加载中…" />
      </div>
    );
  }

  if (!authed) {
    return <Login onLogin={() => setAuthed(true)} />;
  }

  return (
    <BrowserRouter>
      <div className="flex min-h-screen">
        <NavRail />
        <main className="flex-1 min-w-0 px-6 pb-6">
          <Routes>
            <Route path="/" element={<TalentChat />} />
            <Route path="/resume-evaluate" element={<ResumeEvaluate />} />
            <Route path="/knowledge" element={<Navigate to="/" replace />} />
            <Route path="/talent-pool" element={<TalentPool />} />
            <Route path="/talent-pool/:personId" element={<TalentProfile />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
