import { useState } from "react";
import { api } from "@/lib/api";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import LoadingIndicator from "@/components/ui/LoadingIndicator";

interface LoginProps {
  onLogin: () => void;
}

export default function Login({ onLogin }: LoginProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.auth.login(username, password);
      onLogin();
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen p-8 bg-surface">
      <Card variant="elevated" className="w-full max-w-[400px] p-8 text-center">
        <Icon name="radar" size={40} className="text-primary" />
        <h1 className="text-headline mt-3 mb-2">智谱人才研究平台</h1>
        <p className="text-body-sm text-on-surface-variant mb-8">内部人才研究、简历评估与知识管理工具</p>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4 text-left">
          <label className="flex flex-col gap-2">
            <span className="text-label text-on-surface-variant">用户名</span>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
              autoComplete="username"
              placeholder="请输入用户名"
              className="h-12 px-4 rounded-sm border border-outline bg-transparent text-body outline-none focus:border-primary transition-colors placeholder:text-on-surface-variant"
            />
          </label>
          <label className="flex flex-col gap-2">
            <span className="text-label text-on-surface-variant">密码</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              placeholder="请输入密码"
              className="h-12 px-4 rounded-sm border border-outline bg-transparent text-body outline-none focus:border-primary transition-colors placeholder:text-on-surface-variant"
            />
          </label>
          <p className="text-label text-on-surface-variant text-center">
            账户名为姓名全拼小写（如 郭泽新 → guozexin）
          </p>
          <Button type="submit" disabled={loading} className="w-full">
            {loading ? (
              <LoadingIndicator size={18} color="text-on-primary" label="登录中…" />
            ) : (
              "登录"
            )}
          </Button>
        </form>
        {error && <p className="mt-4 text-body-sm text-error min-h-[1.2em]">{error}</p>}
      </Card>
    </div>
  );
}
