import { useState, useEffect, useCallback } from "react";
import PageToolbar from "@/components/layout/PageToolbar";
import Card from "@/components/ui/Card";
import { StatusChip } from "@/components/ui/Chip";
import Icon from "@/components/ui/Icon";
import Button from "@/components/ui/Button";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import SegmentedButtons from "@/components/ui/SegmentedButtons";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useTheme, type ThemeMode } from "@/lib/theme";
import { resetOnboarding } from "@/components/OnboardingTour";
import type { HealthReport } from "@/lib/types";

// 服务状态骨架：health 检测完成前先渲染这些卡片（status=checking）
const HEALTH_SKELETON = [
  "mysql",
  "qdrant",
  "llm",
  "embedding",
  "aminer",
  "crossref",
  "arxiv",
  "openalex",
  "web_search",
].map((name) => ({ name, status: "checking", latency_ms: 0, detail: "", required: false }));

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

/** 每个 Key 对应的服务描述（名称 + 用途 + 图标） */
const KEY_META: Record<string, { label: string; desc: string; icon: string }> = {
  LLM_API_KEY: {
    label: "智谱开放平台",
    desc: "一把 Key 通吃：GLM-5.3-Flash 主模型（文本与多模态），以及 Web Search、Embedding 与云端 OCR",
    icon: "neurology",
  },
  AMINER_API_TOKEN: {
    label: "AMiner 学术平台",
    desc: "论文核验（OpenAlex 兜底）+ 学者画像检索（人才知识调查）",
    icon: "school",
  },
};

/** 判断配置项是否为敏感（值为 {configured, masked} 对象） */
function isSensitive(v: ConfigValue): v is SensitiveValue {
  return v !== null && typeof v === "object" && "configured" in v;
}

export default function Settings() {
  // health=null 表示检测进行中；config={} 表示配置读取中——都不挡页面，
  // 卡片先渲染骨架，结果回来后逐卡片无缝定格
  const [health, setHealth] = useState<HealthReport | null>(null);
  const [config, setConfig] = useState<Record<string, ConfigValue>>({});
  // 正在编辑的 key（一次只能编辑一个）
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editValue, setEditValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    // 两个请求独立失败互不拖累；页面骨架先行，结果逐项填充
    // /health 已是后端缓存优先（秒回上次结果 + 后台刷新），切页不再重复探测
    api.health().then(setHealth).catch(() => setHealth(null));
    api.config.get().then((c) => setConfig(c as Record<string, ConfigValue>)).catch(() => setConfig({}));
  }, []);

  const recheck = useCallback(async () => {
    setHealth(null);
    try {
      setHealth(await api.health());
    } catch {
      setHealth(null);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const { t } = useI18n();
  const { mode: themeMode, setMode: setThemeMode } = useTheme();

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
      setSaveMsg({ ok: true, text: t("{key} 已更新", { key }) });
    } catch {
      setSaveMsg({ ok: false, text: t("{key} 更新失败", { key }) });
    } finally {
      setSaving(false);
    }
  };

  // 配置未返回时先用白名单骨架渲染（值区显示骨架条），返回后无缝替换
  const configEntries: [string, ConfigValue | null][] =
    Object.entries(config).length > 0 ? (Object.entries(config) as [string, ConfigValue][]) : (Object.keys(KEY_META) as string[]).map((k): [string, ConfigValue | null] => [k, null]);

  return (
    <div>
      <PageToolbar title={t("设置")} subtitle={t("外部服务 Key、Base URL 与模型配置")} />
      <div className="flex flex-col gap-6">
          {/* 外观 */}
          <section>
            <h2 className="text-title-lg mb-3">{t("外观")}</h2>
            <Card variant="outlined" className="flex items-center justify-between gap-4 p-4">
              <div className="flex items-center gap-3 min-w-0">
                <Icon name="routine" size={20} className="text-on-surface-variant shrink-0" />
                <div className="min-w-0">
                  <p className="text-title">{t("界面主题")}</p>
                  <p className="text-body-sm text-on-surface-variant">
                    {t("跟随系统时按操作系统外观自动切换")}
                  </p>
                </div>
              </div>
              <SegmentedButtons
                value={themeMode}
                onChange={(v) => setThemeMode(v as ThemeMode)}
                options={[
                  { value: "light", label: t("浅色"), icon: "light_mode" },
                  { value: "dark", label: t("深色"), icon: "dark_mode" },
                  { value: "system", label: t("跟随系统"), icon: "routine" },
                ]}
                className="shrink-0"
              />
            </Card>
          </section>

          {/* 服务状态 */}
          <section>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-title-lg">{t("服务状态")}</h2>
              <div className="flex items-center gap-2">
                {health?.checked_at && (
                  <span className="text-label text-on-surface-variant">
                    {t("检测于 {time}", { time: new Date(health.checked_at + "Z").toLocaleTimeString() })}
                  </span>
                )}
                <Button variant="text" icon="refresh" className="h-7 px-2 text-xs" onClick={recheck}>
                  {t("重新检测")}
                </Button>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3">
              {(health?.services ?? HEALTH_SKELETON).map((s) => {
                const meta = statusMeta[s.status] ?? statusMeta.down;
                return (
                  <Card key={s.name} variant="outlined" className="flex items-center justify-between gap-3 p-4">
                    <div className="flex items-center gap-2 min-w-0">
                      <Icon name={meta.icon} size={18} className={meta.cls} />
                      <span className="text-title truncate">{s.name}</span>
                      {s.required && <StatusChip tone="error">{t("必需")}</StatusChip>}
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

          {/* 外部服务 Key */}
          <section>
            <h2 className="text-title-lg mb-3">{t("外部服务 Key")}</h2>
            {saveMsg && (
              <div className={`mb-3 px-3 py-2 rounded-md text-body-sm ${saveMsg.ok ? "bg-success-container text-success" : "bg-error-container text-error"}`}>
                <Icon name={saveMsg.ok ? "check_circle" : "error"} size={16} className="inline mr-1" />
                {saveMsg.text}
              </div>
            )}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-w-[1040px]">
              {configEntries.map(([key, value]) => {
                const skeleton = value === null || value === undefined;
                const sensitive = !skeleton && isSensitive(value as ConfigValue);
                const isEditing = editingKey === key;
                const meta = KEY_META[key];
                // 从服务状态找对应的健康检查结果
                const svcHealth = health?.services.find((s) => {
                  if (key === "LLM_API_KEY") return s.name === "llm";
                  if (key === "Z_AI_API_KEY") return s.name === "web_search" || s.name === "embedding";
                  if (key === "AMINER_API_TOKEN") return s.name === "aminer";
                  return false;
                });
                return (
                  <Card key={key} variant="outlined" className={`flex flex-col gap-2 p-4 ${isEditing ? "ring-2 ring-primary" : ""}`}>
                    {/* 服务标题行：图标 + 服务名 + 连接状态 */}
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        {meta && <Icon name={meta.icon} size={20} className="text-primary shrink-0" />}
                        <div className="min-w-0">
                          <span className="text-title text-on-surface">{t(meta?.label || key)}</span>
                          <span className="text-label text-on-surface-variant ml-2 font-mono">{key}</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {/* 服务连接状态：检测中转圈，完成定格 */}
                        {svcHealth ? (
                          <span className="inline-flex items-center gap-1 text-label text-on-surface-variant">
                            <span className={`w-2 h-2 rounded-full ${svcHealth.status === "ok" ? "bg-success" : svcHealth.status === "degraded" ? "bg-warning" : "bg-error"}`} />
                            {svcHealth.detail}
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-label text-on-surface-variant">
                            <LoadingIndicator size={14} strokeWidth={2} />
                            {t("检测中…")}
                          </span>
                        )}
                        {sensitive && (value as SensitiveValue).configured && (
                          <StatusChip tone="success">{t("已配置")}</StatusChip>
                        )}
                        {sensitive && !(value as SensitiveValue).configured && (
                          <StatusChip tone="warning">{t("未配置")}</StatusChip>
                        )}
                      </div>
                    </div>
                    {/* 服务用途描述 */}
                    {meta && <p className="text-body-sm text-on-surface-variant">{t(meta.desc)}</p>}
                    {/* 值显示区（敏感项只显示脱敏，非敏感显示原值） */}
                    {!isEditing && (
                      <div className="flex items-center justify-between gap-2">
                        {skeleton ? (
                          <span className="skeleton-block h-3.5 w-40" aria-label="loading" />
                        ) : (
                        <span
                          className={`text-body-sm text-on-surface-variant font-mono truncate min-w-0 ${sensitive ? "select-none" : ""}`}
                          title={sensitive ? (value as SensitiveValue).masked || undefined : (value as string) || undefined}
                        >
                          {sensitive ? (value as SensitiveValue).masked || t("（未配置）") : (value as string) || "—"}
                        </span>
                        )}
                        <Button
                          variant="text"
                          icon="edit"
                          className="h-7 px-2 text-xs shrink-0"
                          onClick={() => startEdit(key)}
                        >
                          {sensitive ? t("更新") : t("编辑")}
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
                          placeholder={sensitive ? t("输入新值（不显示旧值）") : t("输入新值")}
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
                            {saving ? <LoadingIndicator size={14} color="text-on-primary" /> : t("保存")}
                          </Button>
                          <Button
                            variant="text"
                            icon="close"
                            className="h-8 px-3 text-xs"
                            disabled={saving}
                            onClick={cancelEdit}
                          >
                            {t("取消")}
                          </Button>
                        </div>
                      </div>
                    )}
                  </Card>
                );
              })}
            </div>
          </section>

          {/* 其他 */}
          <section>
            <h2 className="text-title-lg mb-3">{t("其他")}</h2>
            <div className="flex gap-3">
              <Button
                variant="outlined"
                icon="school"
                onClick={() => { resetOnboarding(); window.location.href = "/"; }}
              >
                {t("重新查看新手引导")}
              </Button>
            </div>
        </section>
      </div>
    </div>
  );
}
