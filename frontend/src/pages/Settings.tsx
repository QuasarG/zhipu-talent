import { useState, useEffect, useCallback } from "react";
import PageToolbar from "@/components/layout/PageToolbar";
import Card from "@/components/ui/Card";
import { StatusChip } from "@/components/ui/Chip";
import Icon from "@/components/ui/Icon";
import Button from "@/components/ui/Button";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import { api } from "@/lib/api";
import type { HealthReport } from "@/lib/types";

const statusMeta: Record<string, { icon: string; cls: string }> = {
  ok: { icon: "check_circle", cls: "text-success" },
  degraded: { icon: "warning", cls: "text-warning" },
  down: { icon: "error", cls: "text-error" },
};

/** 敏感配置项的脱敏值：只显示 configured + masked，不回显原始值 */
interface SensitiveValue {
  configured: boolean;
  masked: string;
}

type ConfigValue = string | SensitiveValue;

/** 判断配置项是否为敏感（值为 {configured, masked} 对象） */
function isSensitive(v: ConfigValue): v is SensitiveValue {
  return v !== null && typeof v === "object" && "configured" in v;
}

export default function Settings() {
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [config, setConfig] = useState<Record<string, ConfigValue>>({});
  const [loading, setLoading] = useState(true);
  // 正在编辑的 key（一次只能编辑一个）
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [h, c] = await Promise.all([
        api.health(),
        api.config.get(),
      ]);
      setHealth(h);
      setConfig(c as Record<string, ConfigValue>);
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const startEdit = (key: string) => {
    setEditingKey(key);
    // 编辑时清空输入框——不回显旧值（安全要求）
    setEditValue("");
    setSaveMsg(null);
  };

  const cancelEdit = () => {
    setEditingKey(null);
    setEditValue("");
    setSaveMsg(null);
  };

  const saveEdit = async (key: string) => {
    setSaving(true);
    setSaveMsg(null);
    try {
      await api.config.put({ [key]: editValue });
      // 重新拉取脱敏配置（不会回显刚写入的值，只显示 configured + masked）
      const c = await api.config.get();
      setConfig(c as Record<string, ConfigValue>);
      setEditingKey(null);
      setEditValue("");
      setSaveMsg({ ok: true, text: `${key} 已更新` });
    } catch {
      setSaveMsg({ ok: false, text: `${key} 更新失败` });
    } finally {
      setSaving(false);
    }
  };

  const configEntries = Object.entries(config);

  return (
    <div>
      <PageToolbar title="设置" subtitle="外部服务 Key、Base URL 与模型配置" />
      {loading ? (
        <div className="flex items-center justify-center py-24">
          <LoadingIndicator size={32} label="加载中…" />
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          {/* 服务状态 */}
          <section>
            <h2 className="text-title-lg mb-3">服务状态</h2>
            <div className="grid grid-cols-3 gap-3">
              {health?.services.map((s) => {
                const meta = statusMeta[s.status] ?? statusMeta.down;
                return (
                  <Card key={s.name} variant="outlined" className="flex items-center justify-between gap-3 p-4">
                    <div className="flex items-center gap-2 min-w-0">
                      <Icon name={meta.icon} size={18} className={meta.cls} />
                      <span className="text-title truncate">{s.name}</span>
                      {s.required && <StatusChip tone="error">必需</StatusChip>}
                    </div>
                    <div className="flex flex-col items-end gap-0.5 shrink-0">
                      <span className="font-mono text-body-sm text-on-surface-variant">{Math.round(s.latency_ms)}ms</span>
                      <span className="font-mono text-label text-on-surface-variant truncate max-w-[160px]" title={s.detail}>
                        {s.detail}
                      </span>
                    </div>
                  </Card>
                );
              })}
            </div>
          </section>

          {/* 配置项 */}
          <section>
            <h2 className="text-title-lg mb-3">配置项</h2>
            {saveMsg && (
              <div className={`mb-3 px-3 py-2 rounded-md text-body-sm ${saveMsg.ok ? "bg-success-container text-success" : "bg-error-container text-error"}`}>
                <Icon name={saveMsg.ok ? "check_circle" : "error"} size={16} className="inline mr-1" />
                {saveMsg.text}
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              {configEntries.map(([key, value]) => {
                const sensitive = isSensitive(value);
                const isEditing = editingKey === key;
                return (
                  <Card key={key} variant="outlined" className={`flex flex-col gap-1 p-4 ${isEditing ? "ring-2 ring-primary" : ""}`}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-label text-on-surface">{key}</span>
                      {/* 状态标记 */}
                      {sensitive ? (
                        <StatusChip tone={value.configured ? "success" : "warning"}>
                          {value.configured ? "已配置" : "未配置"}
                        </StatusChip>
                      ) : null}
                    </div>
                    {/* 值显示区（敏感项只显示脱敏，非敏感显示原值） */}
                    {!isEditing && (
                      <div className="flex items-center justify-between gap-2">
                        <span className={`text-body text-on-surface-variant font-mono ${sensitive ? "select-none" : ""}`}>
                          {sensitive ? value.masked || "（未配置）" : value || "—"}
                        </span>
                        <Button
                          variant="text"
                          icon="edit"
                          className="h-7 px-2 text-xs shrink-0"
                          onClick={() => startEdit(key)}
                        >
                          {sensitive ? "更新" : "编辑"}
                        </Button>
                      </div>
                    )}
                    {/* 内联编辑区 */}
                    {isEditing && (
                      <div className="flex flex-col gap-2 mt-1">
                        <input
                          type={sensitive ? "password" : "text"}
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          autoFocus
                          placeholder={sensitive ? "输入新值（不显示旧值）" : "输入新值"}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && editValue) saveEdit(key);
                            if (e.key === "Escape") cancelEdit();
                          }}
                          className="h-9 px-3 rounded-sm border border-outline bg-transparent text-body-sm outline-none focus:border-primary placeholder:text-on-surface-variant font-mono"
                        />
                        <div className="flex items-center gap-2">
                          <Button
                            variant="filled"
                            icon="check"
                            className="h-8 px-3 text-xs"
                            disabled={!editValue || saving}
                            onClick={() => saveEdit(key)}
                          >
                            {saving ? <LoadingIndicator size={14} color="text-on-primary" /> : "保存"}
                          </Button>
                          <Button
                            variant="text"
                            icon="close"
                            className="h-8 px-3 text-xs"
                            disabled={saving}
                            onClick={cancelEdit}
                          >
                            取消
                          </Button>
                        </div>
                      </div>
                    )}
                  </Card>
                );
              })}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
