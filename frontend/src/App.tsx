import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useState, useEffect } from "react";
import { api } from "./lib/api";
import NavRail from "./components/layout/NavRail";
import Login from "./pages/Login";
import ResumeEvaluate from "./pages/ResumeEvaluate";
import KnowledgeAgent from "./pages/KnowledgeAgent";
import TalentPool from "./pages/TalentPool";
import ReviewCenter from "./pages/ReviewCenter";
import Settings from "./pages/Settings";

function App() {
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    api.auth.status().then((d) => setAuthed(d.authenticated));
  }, []);

  if (authed === null) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-body text-on-surface-variant">加载中…</p>
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
            <Route path="/" element={<ResumeEvaluate />} />
            <Route path="/knowledge" element={<KnowledgeAgent />} />
            <Route path="/talent-pool" element={<TalentPool />} />
            <Route path="/review" element={<ReviewCenter />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
