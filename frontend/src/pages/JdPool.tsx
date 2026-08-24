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

/** JD 池：每个激活 JD 都会与每份简历独立产出面试准入结论。 */
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
        subtitle={t("{count} 个激活 JD 将分别参与后续面试准入评估", { count: activeCount })}
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
            {t("添加并激活 JD 后，每份简历都会针对各岗位独立判断是否进入面试")}
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

function JdCard({ jd, expanded, busy, onToggle, onActivate, onArchive, onEdit, onDelete, t }: {
  jd: JdEntry;
  expanded: boolean;
  busy: boolean;
  onToggle: () => void;
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
        <span className="ml-auto flex items-center gap-1.5 shrink-0" onClick={(e) => e.stopPropagation()}>
          {jd.status !== "active" && (
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
      {/* 展开区：JD 原文 + 固定准入语义 */}
      {expanded && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 px-4 pb-4 border-t border-outline-variant pt-3">
          <div className="min-w-0">
            <p className="text-label text-on-surface-variant mb-1.5">{t("JD 原文")}</p>
            <pre className="text-body-sm text-on-surface whitespace-pre-wrap break-words max-h-80 overflow-y-auto bg-surface-lowest rounded-md p-3">
              {jd.raw_text}
            </pre>
          </div>
          <div className="min-w-0">
            <p className="text-label text-on-surface-variant mb-1.5">{t("准入评估方式")}</p>
            <div className="rounded-md bg-surface-lowest p-3 text-body-sm leading-6 text-on-surface">
              <p>{t("系统会先逐条核对 JD 硬门槛，再评估直接任务匹配、技术深度、本人贡献、证据质量、工程规模和可迁移性。")}</p>
              <p className="mt-2 text-on-surface-variant">{t("简历未写明的条件标记为待确认；多个 JD 独立判断，不再合并成一个 Track 总分。")}</p>
            </div>
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
  // stage：新建时一键三连（解析→保存→起草）分阶段提示
  const [stage, setStage] = useState<"parse" | "save" | "draft" | null>(null);
  const [error, setError] = useState("");
  const { t } = useI18n();

  const parse = async () => {
    if (!form.raw_text.trim() || stage) return;
    setStage("parse");
    setError("");
    try {
      const brief = await api.jds.parse(form.raw_text.trim());
      setForm((p) => ({ ...p, title: brief.title || p.title, team: brief.team || p.team }));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("解析失败"));
    } finally {
      setStage(null);
    }
  };

  const submit = async () => {
    if (!form.raw_text.trim() || stage) return;
    setError("");
    try {
      if (jd) {
        setStage("save");
        await api.jds.update(jd.id, form);
      } else {
        // 新建：标题留空先自动解析补齐，然后保存 JD。
        let title = form.title.trim();
        let team = form.team.trim();
        if (!title) {
          setStage("parse");
          const brief = await api.jds.parse(form.raw_text.trim());
          title = brief.title;
          team = team || brief.team;
        }
        setStage("save");
        await api.jds.create({ title: title || t("未命名 JD"), team, raw_text: form.raw_text.trim() });
      }
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("保存失败"));
    } finally {
      setStage(null);
    }
  };

  const busyText = stage === "parse" ? t("智能解析中…") : t("保存中…");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-inverse-surface/30" onClick={onClose}>
      <Card variant="elevated" className="w-[560px] max-h-[85vh] p-5 flex flex-col gap-3" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <p className="text-title-lg">{jd ? t("编辑 JD") : t("添加 JD")}</p>
          <IconButton icon="close" onClick={onClose} title={t("关闭")} />
        </div>
        <textarea
          value={form.raw_text}
          onChange={(e) => setForm((p) => ({ ...p, raw_text: e.target.value }))}
          placeholder={t("直接粘贴 JD 全文（必填）：团队介绍、工作内容、职位要求、加分项……")}
          className={cn(inputClass, "min-h-56 resize-y")}
          autoFocus
        />
        <div className="flex items-center gap-2">
          <Button variant="text" icon="neurology" className="h-8 px-2 text-xs" disabled={!form.raw_text.trim() || stage !== null} onClick={parse}>
            {stage === "parse" ? t("智能解析中…") : t("智能解析标题/团队")}
          </Button>
          <span className="text-label text-on-surface-variant">{t("解析结果可手动修改")}</span>
        </div>
        <input
          type="text"
          value={form.title}
          onChange={(e) => setForm((p) => ({ ...p, title: e.target.value }))}
          placeholder={t("岗位标题（留空则保存时自动解析）")}
          className={cn(inputClass, "h-9")}
        />
        <input
          type="text"
          value={form.team}
          onChange={(e) => setForm((p) => ({ ...p, team: e.target.value }))}
          placeholder={t("团队 / 研究组")}
          className={cn(inputClass, "h-9")}
        />
        {jd && jd.status === "active" && (
          <p className="text-label text-on-surface-variant">{t("修改原文后 spec 失效，该 JD 将退回草稿待重新起草")}</p>
        )}
        {error && <p className="text-label text-error">{error}</p>}
        <Button variant="tonal" icon="save" className="w-full" disabled={!form.raw_text.trim() || stage !== null} onClick={submit}>
          {stage ? busyText : jd ? t("保存") : t("保存 JD")}
        </Button>
      </Card>
    </div>
  );
}
