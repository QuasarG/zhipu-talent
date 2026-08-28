import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { JdEntry } from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import Button, { IconButton } from "@/components/ui/Button";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import { StatusChip } from "@/components/ui/Chip";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/cn";

const inputClass = "px-3 py-2 rounded-sm border border-outline-variant bg-surface-lowest text-body-sm text-on-surface outline-none focus:outline-2 focus:outline-primary";
const importanceLabel = { primary: "首要", major: "主要", supporting: "补充" } as const;

export default function JdPool() {
  const [jds, setJds] = useState<JdEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<JdEntry | "new" | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const { t } = useI18n();
  const load = useCallback(async () => {
    try { setJds(await api.jds.list()); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("加载失败")); }
    finally { setLoading(false); }
  }, [t]);
  useEffect(() => { void load(); }, [load]);

  // 稳定展示序：未归档在前，同组内按更新时间倒序（最近维护的优先可见）
  const ordered = [...jds].sort((a, b) => {
    if (!!a.archived !== !!b.archived) return a.archived ? 1 : -1;
    return (b.updated_at || "").localeCompare(a.updated_at || "");
  });

  return <div className="w-full flex flex-col gap-4">
    <PageToolbar title={t("JD 池")} subtitle={t("JD 入池即生成岗位评估卡；是否参与评估由每次批次显式选择")} right={<><IconButton icon="refresh" variant="outlined" onClick={load} title={t("刷新")} /><Button variant="filled" icon="add" onClick={() => setEditing("new")}>{t("添加 JD")}</Button></>} />
    {error && <p className="text-body-sm text-error px-2">{error}</p>}
    {loading ? <div className="flex justify-center py-20"><LoadingIndicator size={28} /></div> : <div className="flex flex-col gap-3 pb-6">
      {ordered.map((jd) => <JdCard key={jd.id} jd={jd} expanded={expandedId === jd.id} onToggle={() => setExpandedId(expandedId === jd.id ? null : jd.id)} onEdit={() => setEditing(jd)} onArchive={async () => { await api.jds.setArchived(jd.id, !jd.archived); await load(); }} onDelete={async () => { await api.jds.delete(jd.id); await load(); }} />)}
      {!jds.length && <Card variant="filled" className="py-16 text-center text-on-surface-variant">{t("JD 池为空")}</Card>}
    </div>}
    {editing && <JdEditor jd={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); void load(); }} />}
  </div>;
}

function JdCard({ jd, expanded, onToggle, onEdit, onArchive, onDelete }: { jd: JdEntry; expanded: boolean; onToggle: () => void; onEdit: () => void; onArchive: () => void; onDelete: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const card = jd.assessment_card;
  return <Card variant="filled" className={cn("flex flex-col", jd.archived && "opacity-60")}>
    <div className="flex items-center gap-3 px-4 min-h-14 cursor-pointer" onClick={onToggle}>
      <Icon name={expanded ? "expand_less" : "expand_more"} size={18} /><span className="text-title truncate">{jd.title}</span>
      {jd.team && <span className="text-body-sm text-on-surface-variant truncate">{jd.team}</span>}
      <StatusChip tone={jd.card_status === "ready" ? "success" : jd.card_status === "failed" ? "error" : "primary"}>{jd.card_status === "ready" ? "评估卡就绪" : jd.card_status === "failed" ? "生成失败" : "生成中"}</StatusChip>
      {jd.archived && <StatusChip tone="neutral">已归档</StatusChip>}
      <span className="ml-auto flex gap-1" onClick={(event) => event.stopPropagation()}><IconButton icon="edit" onClick={onEdit} title="编辑并重新生成" /><IconButton icon={jd.archived ? "unarchive" : "archive"} onClick={onArchive} title={jd.archived ? "恢复" : "归档"} />{confirming ? <Button variant="text" className="text-error" onClick={onDelete}>确认删除</Button> : <IconButton icon="delete" onClick={() => setConfirming(true)} title="删除" />}</span>
    </div>
    {expanded && <div className="grid grid-cols-1 xl:grid-cols-[0.8fr_1.2fr] gap-4 border-t border-outline-variant p-4">
      <div><p className="text-label text-on-surface-variant mb-2">JD 原文</p><pre className="max-h-96 overflow-y-auto whitespace-pre-wrap rounded-md bg-surface-lowest p-3 text-body-sm">{jd.raw_text}</pre></div>
      <div><p className="text-label text-on-surface-variant mb-2">当前岗位评估卡</p>{card?.core_tasks?.length ? <div className="flex flex-col gap-2"><p className="text-body-sm">{card.role_summary}</p>{card.core_tasks.map((task) => <details key={task.id} className="rounded-md bg-surface-lowest p-3"><summary className="list-none cursor-pointer flex gap-2 items-center"><StatusChip tone={task.importance === "primary" ? "error" : task.importance === "major" ? "primary" : "neutral"}>{importanceLabel[task.importance]}</StatusChip><span className="text-title">{task.title}</span></summary><p className="text-body-sm mt-2">{task.description}</p><p className="text-label text-on-surface-variant mt-2">评价重点：{task.evaluation_focus}</p><div className="mt-2 grid grid-cols-3 gap-2 text-label"><span>2 · {task.anchors.level_2}</span><span>3 · {task.anchors.level_3}</span><span>4 · {task.anchors.level_4}</span></div></details>)}{!!jd.supplements.length && <p className="text-label text-on-surface-variant">补充要求：{jd.supplements.join("；")}</p>}</div> : <p className="text-body-sm text-error">{jd.card_error || "岗位评估卡尚未生成"}</p>}</div>
    </div>}
  </Card>;
}

function JdEditor({ jd, onClose, onSaved }: { jd: JdEntry | null; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = useState({ title: jd?.title || "", team: jd?.team || "", raw_text: jd?.raw_text || "" });
  const [supplements, setSupplements] = useState<string[]>(jd?.supplements || []);
  const [newSupplement, setNewSupplement] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async () => {
    if (!form.raw_text.trim() || busy) return;
    setBusy(true); setError("");
    try {
      let title = form.title.trim(); let team = form.team.trim();
      if (!title) { const brief = await api.jds.parse(form.raw_text); title = brief.title || "未命名 JD"; team ||= brief.team; }
      if (jd) await api.jds.update(jd.id, { title, team, raw_text: form.raw_text, supplements }); else await api.jds.create({ title, team, raw_text: form.raw_text });
      onSaved();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "保存失败"); }
    finally { setBusy(false); }
  };
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-inverse-surface/30" onClick={busy ? undefined : onClose}><Card variant="elevated" className="w-[680px] max-h-[88vh] overflow-y-auto p-5 flex flex-col gap-3" onClick={(event) => event.stopPropagation()}>
    <div className="flex items-center justify-between"><p className="text-title-lg">{jd ? "编辑 JD 并重新生成岗位卡" : "添加 JD"}</p>{!busy && <IconButton icon="close" onClick={onClose} title="关闭" />}</div>
    <textarea value={form.raw_text} onChange={(event) => setForm({ ...form, raw_text: event.target.value })} className={cn(inputClass, "min-h-56 resize-y")} placeholder="粘贴 JD 全文" />
    <div className="grid grid-cols-2 gap-2"><input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} className={inputClass} placeholder="岗位标题" /><input value={form.team} onChange={(event) => setForm({ ...form, team: event.target.value })} className={inputClass} placeholder="团队" /></div>
    {jd && <div className="rounded-md bg-surface-low p-3"><p className="text-label mb-2">累计补充要求（保存时与 JD 一起重新生成岗位卡）</p><div className="flex flex-wrap gap-2">{supplements.map((item, index) => <button key={`${item}-${index}`} onClick={() => setSupplements(supplements.filter((_, i) => i !== index))} className="rounded-full bg-secondary-container px-3 py-1 text-label cursor-pointer">{item} ×</button>)}</div><div className="flex gap-2 mt-2"><input value={newSupplement} onChange={(event) => setNewSupplement(event.target.value)} className={cn(inputClass, "flex-1")} placeholder="补充一条能力要求" /><Button variant="tonal" onClick={() => { if (newSupplement.trim()) { setSupplements([...supplements, newSupplement.trim()]); setNewSupplement(""); } }}>添加</Button></div></div>}
    {error && <p className="text-body-sm text-error">{error}</p>}<Button variant="filled" icon="auto_awesome" disabled={busy || !form.raw_text.trim()} onClick={submit}>{busy ? "正在生成并质检岗位卡…" : "保存并生成岗位评估卡"}</Button>
  </Card></div>;
}
