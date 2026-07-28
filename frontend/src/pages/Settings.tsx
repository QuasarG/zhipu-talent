import { useState, useEffect } from "react";
import PageToolbar from "@/components/layout/PageToolbar";
import { api } from "@/lib/api";
import type { HealthReport } from "@/lib/types";
import { CheckCircle, AlertTriangle, XCircle } from "lucide-react";

export default function Settings() {
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [config, setConfig] = useState<Record<string, unknown>>({});

  useEffect(() => {
    api.health().then(setHealth).catch(() => {});
    api.config.get().then(setConfig).catch(() => {});
  }, []);

  const statusIcon = (status: string) => {
    if (status === "ok") return <CheckCircle size={14} className="text-teal" />;
    if (status === "degraded") return <AlertTriangle size={14} className="text-amber-glow" />;
    return <XCircle size={14} className="text-coral" />;
  };

  return (
    <div>
      <PageToolbar title="设置" subtitle="外部服务 Key、Base URL 与模型配置" />
      <div className="space-y-6">
        <section>
          <h2 className="text-base mb-3">服务状态</h2>
          <div className="grid grid-cols-2 gap-3">
            {health?.services.map((s) => (
              <div
                key={s.name}
                className="flex items-center justify-between p-3 rounded-[10px] bg-surface-paper border border-ink/10"
              >
                <div className="flex items-center gap-2">
                  {statusIcon(s.status)}
                  <span className="text-sm font-medium">{s.name}</span>
                  {s.required && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-coral-soft text-coral">
                      必需
                    </span>
                  )}
                </div>
                <span className="text-xs text-ink-secondary font-mono">{s.detail}</span>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h2 className="text-base mb-3">配置项（脱敏）</h2>
          <div className="grid grid-cols-2 gap-3">
            {Object.entries(config).map(([key, val]) => (
              <div
                key={key}
                className="flex flex-col gap-1 p-3 rounded-[10px] bg-surface-paper border border-ink/10"
              >
                <span className="text-xs font-medium">{key}</span>
                <span className="text-xs text-ink-secondary font-mono">
                  {typeof val === "object" && val !== null
                    ? `${(val as Record<string, unknown>).configured ? "已配置" : "未配置"} · ${(val as Record<string, unknown>).masked ?? ""}`
                    : String(val)}
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
