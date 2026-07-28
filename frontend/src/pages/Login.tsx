import { useState } from "react";
import { api } from "@/lib/api";
import GlassPanel from "@/components/glass/GlassPanel";

interface LoginProps {
  onLogin: () => void;
}

export default function Login({ onLogin }: LoginProps) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.auth.login(password);
      onLogin();
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen p-8">
      <GlassPanel variant="strong" className="w-full max-w-[400px] p-10 text-center rounded-[20px]">
        <h1 className="text-2xl mb-2">智谱人才研究平台</h1>
        <p className="text-sm text-ink-secondary mb-8">内部人才研究、简历评估与知识管理工具</p>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4 text-left">
          <label className="flex flex-col gap-2">
            <span className="text-xs text-ink-secondary font-medium">访问密码</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoFocus
              autoComplete="current-password"
              placeholder="请输入访问密码"
              className="px-3 py-2 rounded-[10px] border border-ink/10 bg-white/40 text-sm outline-none focus:border-teal transition-colors"
            />
          </label>
          <button
            type="submit"
            disabled={loading}
            className="px-6 py-2.5 rounded-[10px] border-none bg-teal text-white text-sm font-semibold cursor-pointer hover:bg-teal-light transition-colors disabled:opacity-50"
          >
            {loading ? "登录中…" : "登录"}
          </button>
        </form>
        {error && <p className="mt-4 text-sm text-coral min-h-[1.2em]">{error}</p>}
      </GlassPanel>
    </div>
  );
}
