import { useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import LangToggle from "@/components/LangToggle";

interface LoginProps {
  onLogin: () => void;
}

export default function Login({ onLogin }: LoginProps) {
  const { t } = useI18n();
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
      setError(err instanceof Error ? err.message : t("登录失败"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center min-h-screen p-8 bg-surface">
      <Card variant="elevated" className="relative w-full max-w-[400px] p-8 text-center">
        <LangToggle className="absolute top-4 right-4 h-8 px-3 rounded-md border border-outline-variant bg-surface-lowest" />
        <Icon name="radar" size={40} className="text-primary" />
        <h1 className="text-headline mt-3 mb-2">{t("智谱人才研究平台")}</h1>
        <p className="text-body-sm text-on-surface-variant mb-8">
          {t("内部人才研究、简历评估与知识管理工具")}
        </p>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4 text-left">
          <label className="flex flex-col gap-2">
            <span className="text-label text-on-surface-variant">{t("用户名")}</span>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
              autoComplete="username"
              placeholder={t("请输入用户名")}
              className="h-12 px-4 rounded-sm border border-outline bg-transparent text-body outline-none focus:border-primary transition-colors placeholder:text-on-surface-variant"
            />
          </label>
          <label className="flex flex-col gap-2">
            <span className="text-label text-on-surface-variant">{t("密码")}</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              placeholder={t("请输入密码")}
              className="h-12 px-4 rounded-sm border border-outline bg-transparent text-body outline-none focus:border-primary transition-colors placeholder:text-on-surface-variant"
            />
          </label>
          <p className="text-label text-on-surface-variant text-center">
            {t("账户名为姓名全拼小写（如 郭泽新 → guozexin）")}
          </p>
          <Button type="submit" disabled={loading} className="w-full">
            {loading ? (
              <LoadingIndicator size={18} color="text-on-primary" label={t("登录中…")} />
            ) : (
              t("登录")
            )}
          </Button>
        </form>
        {error && <p className="mt-4 text-body-sm text-error min-h-[1.2em]">{error}</p>}
      </Card>
    </div>
  );
}
