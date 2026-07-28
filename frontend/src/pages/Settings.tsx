import { useState, useEffect } from "react";
import PageToolbar from "@/components/layout/PageToolbar";
import Card from "@/components/ui/Card";
import { StatusChip } from "@/components/ui/Chip";
import Icon from "@/components/ui/Icon";
import { api } from "@/lib/api";
import type { HealthReport } from "@/lib/types";

const statusMeta: Record<string, { icon: string; cls: string }> = {
  ok: { icon: "check_circle", cls: "text-success" },
  degraded: { icon: "warning", cls: "text-warning" },
  down: { icon: "error", cls: "text-error" },
};

export default function Settings() {
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [config, setConfig] = useState<Record<string, unknown>>({});

  useEffect(() => {
    api.health().then(setHealth).catch(() => {});
    api.config.get().then(setConfig).catch(() => {});
  }, []);

  return (
    <div>
      <PageToolbar title="设置" subtitle="外部服务 Key、Base URL 与模型配置" />
      <div className="flex flex-col gap-6">
        <section>
          <h2 className="text-title-lg mb-3">服务状态</h2>
          <div className="grid grid-cols-2 gap-3">
            {health?.services.map((s) => {
              const meta = statusMeta[s.status] ?? statusMeta.down;
              return (
                <Card key={s.name} variant="filled" className="flex items-center justify-between p-3">
                  <div className="flex items-center gap-2">
                    <Icon name={meta.icon} size={18} className={meta.cls} />
                    <span className="text-title">{s.name}</span>
                    {s.required && <StatusChip tone="error">必需</StatusChip>}
                  </div>
                  <div className="flex items-center gap-3 text-body-sm text-on-surface-variant">
                    <span className="font-mono">{s.detail}</span>
                    <span className="font-mono">{Math.round(s.latency_ms)}ms</span>
                  </div>
                </Card>
              );
            })}
          </div>
        </section>

        <section>
          <h2 className="text-title-lg mb-3">配置项（脱敏）</h2>
          <div className="grid grid-cols-2 gap-3">
            {Object.entries(config).map(([key, val]) => (
              <Card key={key} variant="outlined" className="flex flex-col gap-1 p-3">
                <span className="text-label text-on-surface">{key}</span>
                <span className="text-body-sm text-on-surface-variant font-mono">
                  {typeof val === "object" && val !== null
                    ? `${(val as Record<string, unknown>).configured ? "已配置" : "未配置"} · ${(val as Record<string, unknown>).masked ?? ""}`
                    : String(val)}
                </span>
              </Card>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
