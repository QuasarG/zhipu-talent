import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { JdEntry } from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import Button, { IconButton } from "@/components/ui/Button";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/cn";

const STATUS_STYLE: Record<string, { label: string; className: string }> = {
  draft: { label: "草稿", className: "bg-surface-low text-on-surface-variant" },
  active: { label: "已激活", className: "bg-primary-container text-on-primary-container" },
  archived: { label: "已停用", className: "bg-surface-low text-on-surface-variant line-through" },
};

const inputClass =
  "px-3 py-2 rounded-sm border border-outline-variant bg-surface-lowest text-body-sm text-on-surface outline-none focus:outline-2 focus:outline-primary";

/** JD 池：激活的 JD 即一个岗位 Track，实时参与后续评估的多 track 打分 */
export default function JdPool() {
  const [jds, setJds] = useState<JdEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<JdEntry | "new" | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const { t } = useI18n();

  const load = useCallback(async () => {
    try {
      setJds(await api.jds.list());
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("加载失败"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (id: string, fn: () => Promise<unknown>) => {
    if (busyId) return;
    setBusyId(id);
    setError("");
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("操作失败"));
    } finally {
      setBusyId(null);
    }
  };

  const activeCount = jds.filter((j) => j.status === "active").length;

  return (
    <div className="w-full max-w-full min-h-0 flex flex-col gap-4">
      <PageToolbar
        title={t("JD 池")}
        subtitle={t("激活的 JD 即岗位 Track（共 {count} 个激活），实时参与后续评估", { count: activeCount })}
        right={
          <>
            <IconButton icon="refresh" variant="outlined" onClick={load} title={t("刷新")} />
            <Button variant="filled" icon="add" onClick={() => setEditing("new")}>
              {t("添加 JD")}
            </Button>
          </>
        }
      />
      {error && <p className="text-body-sm text-error px-2">{error}</p>}
      {loading ? (
        <div className="flex justify-center py-20">
          <LoadingIndicator size={28} />
        </div>
      ) : jds.length === 0 ? (
        <Card variant="filled" className="flex flex-col items-center py-16 gap-2">
          <Icon name="work" size={32} className="text-on-surface-variant" />
          <p className="text-body text-on-surface">{t("JD 池为空")}</p>
          <p className="text-body-sm text-on-surface-variant">
            {t("添加 JD 并起草、激活 spec 后，评估将按岗位 Track 打分；池为空时只产出通用潜力分")}
          </p>
        </Card>
      ) : (
        <div className="flex flex-col gap-3 pb-6">
          {jds.map((jd) => (
            <JdCard
              key={jd.id}
              jd={jd}
              expanded={expandedId === jd.id}
              busy={busyId === jd.id}
              onToggle={() => setExpandedId(expandedId === jd.id ? null : jd.id)}
              onGenerate={() => act(jd.id, () => api.jds.generateSpec(jd.id))}
              onActivate={() => act(jd.id, () => api.jds.setStatus(jd.id, "active"))}
              onArchive={() => act(jd.id, () => api.jds.setStatus(jd.id, "archived"))}
              onEdit={() => setEditing(jd)}
              onDelete={() => act(jd.id, () => api.jds.delete(jd.id))}
              t={t}
            />
          ))}
        </div>
      )}
      {editing && (
        <JdEditDialog
          jd={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void load();
          }}
        />
      )}
    </div>
  );
}

function JdCard({ jd, expanded, busy, onToggle, onGenerate, onActivate, onArchive, onEdit, onDelete, t }: {
  jd: JdEntry;
  expanded: boolean;
  busy: boolean;
  onToggle: () => void;
  onGenerate: () => void;
  onActivate: () => void;
  onArchive: () => void;
  onEdit: () => void;
  onDelete: () => void;
  t: (k: string, p?: Record<string, string | number>) => string;
}) {
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const status = STATUS_STYLE[jd.status] || STATUS_STYLE.draft;
  return (
    <Card variant="filled" className="flex flex-col">
      {/* 头部行：标题 + 状态 + 操作 */}
      <div className="flex items-center gap-3 px-4 h-14 cursor-pointer select-none" onClick={onToggle}>
        <Icon name={expanded ? "expand_less" : "expand_more"} size={18} className="text-on-surface-variant shrink-0" />
        <span className="text-title text-on-surface truncate">{jd.title}</span>
        {jd.team && <span className="text-body-sm text-on-surface-variant truncate">{jd.team}</span>}
        <span className={cn("text-label px-2 py-0.5 rounded-full shrink-0", status.className)}>{t(status.label)}</span>
        {jd.spec && (
          <span className="text-label text-on-surface-variant shrink-0">
            {jd.spec.label} · v{jd.spec_version} · {t("{count} 维度", { count: jd.spec.dimensions.length })}
          </span>
        )}
        <span className="ml-auto flex items-center gap-1.5 shrink-0" onClick={(e) => e.stopPropagation()}>
          <Button variant="text" icon="neurology" className="h-8 px-2 text-xs" disabled={busy} onClick={onGenerate}>
            {busy ? t("起草中…") : jd.spec ? t("重新起草") : t("起草 spec")}
          </Button>
          {jd.status !== "active" && jd.spec && (
            <Button variant="tonal" icon="check_circle" className="h-8 px-2 text-xs" disabled={busy} onClick={onActivate}>
              {t("激活")}
            </Button>
          )}
          {jd.status === "active" && (
            <Button variant="text" icon="cancel" className="h-8 px-2 text-xs" disabled={busy} onClick={onArchive}>
              {t("停用")}
            </Button>
          )}
          <IconButton icon="edit" onClick={onEdit} title={t("编辑")} />
          {confirmingDelete ? (
            <>
              <Button variant="text" className="h-8 px-2 text-xs text-error" disabled={busy} onClick={onDelete}>
                {t("确认删除")}
              </Button>
              <IconButton icon="close" onClick={() => setConfirmingDelete(false)} title={t("取消")} />
            </>
          ) : (
            <IconButton icon="delete" onClick={() => setConfirmingDelete(true)} title={t("删除")} />
          )}
        </span>
      </div>
      {/* 展开区：原文 + spec 明细 */}
      {expanded && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 px-4 pb-4 border-t border-outline-variant pt-3">
          <div className="min-w-0">
            <p className="text-label text-on-surface-variant mb-1.5">{t("JD 原文")}</p>
            <pre className="text-body-sm text-on-surface whitespace-pre-wrap break-words max-h-80 overflow-y-auto bg-surface-lowest rounded-md p-3">
              {jd.raw_text}
            </pre>
          </div>
          <div className="min-w-0">
            <p className="text-label text-on-surface-variant mb-1.5">{t("Track Spec（评估规格）")}</p>
            {jd.spec ? (
              <div className="flex flex-col gap-2 text-body-sm">
                <p className="text-on-surface">
                  <span className="font-semibold">{jd.spec.label}</span>
                  <span className="text-on-surface-variant">（{jd.spec.key}）</span>
                </p>
                <p className="text-on-surface-variant">{jd.spec.evidence_focus}</p>
                <p className="text-on-surface-variant">{t("高分规则：")}{jd.spec.high_score_rule}</p>
                <div className="flex flex-col gap-1">
                  {jd.spec.dimensions.map((d) => (
                    <div key={d.key} className="flex items-baseline gap-2 bg-surface-lowest rounded-md px-3 py-2">
                      <span className="text-on-surface font-medium shrink-0">{d.label}</span>
                      <span className="text-label text-primary tabular-nums shrink-0">{d.max_points} 分</span>
                      <span className="text-label text-on-surface-variant truncate">{d.evidence_rule}</span>
                    </div>
                  ))}
                </div>
                {jd.spec.keywords && jd.spec.keywords.length > 0 && (
                  <p className="text-label text-on-surface-variant">
                    {t("路由关键词：")}{jd.spec.keywords.join(" / ")}
                  </p>
                )}
              </div>
            ) : (
              <p className="text-body-sm text-on-surface-variant">{t("尚未起草 spec——点击「起草 spec」由 LLM 生成，确认无误后激活")}</p>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

function JdEditDialog({ jd, onClose, onSaved }: { jd: JdEntry | null; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({
    title: jd?.title || "",
    team: jd?.team || "",
    raw_text: jd?.raw_text || "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const { t } = useI18n();

  const submit = async () => {
    if (!form.title.trim() || !form.raw_text.trim() || saving) return;
    setSaving(true);
    setError("");
    try {
      if (jd) await api.jds.update(jd.id, form);
      else await api.jds.create(form);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("保存失败"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-inverse-surface/30" onClick={onClose}>
      <Card variant="elevated" className="w-[560px] max-h-[85vh] p-5 flex flex-col gap-3" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <p className="text-title-lg">{jd ? t("编辑 JD") : t("添加 JD")}</p>
          <IconButton icon="close" onClick={onClose} title={t("关闭")} />
        </div>
        <input
          type="text"
          value={form.title}
          onChange={(e) => setForm((p) => ({ ...p, title: e.target.value }))}
          placeholder={t("岗位标题（必填），如：多模态生成算法研究")}
          className={cn(inputClass, "h-9")}
        />
        <input
          type="text"
          value={form.team}
          onChange={(e) => setForm((p) => ({ ...p, team: e.target.value }))}
          placeholder={t("团队 / 研究组")}
          className={cn(inputClass, "h-9")}
        />
        <textarea
          value={form.raw_text}
          onChange={(e) => setForm((p) => ({ ...p, raw_text: e.target.value }))}
          placeholder={t("JD 原文（必填）：团队介绍、工作内容、职位要求、加分项……")}
          className={cn(inputClass, "min-h-56 resize-y")}
        />
        {jd && jd.status === "active" && (
          <p className="text-label text-on-surface-variant">{t("修改原文后 spec 失效，该 JD 将退回草稿待重新起草")}</p>
        )}
        {error && <p className="text-label text-error">{error}</p>}
        <Button variant="tonal" icon="save" className="w-full" disabled={!form.title.trim() || !form.raw_text.trim() || saving} onClick={submit}>
          {saving ? t("保存中…") : t("保存")}
        </Button>
      </Card>
    </div>
  );
}
