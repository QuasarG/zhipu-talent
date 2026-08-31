// 奖学金资料工作台：申请人信息 / 材料预览 / 评估与核验
import { Fragment, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { ScholarshipApplication, ScholarshipMaterial } from "@/lib/types";
import Button, { IconButton } from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import { StatusChip } from "@/components/ui/Chip";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import Progress from "@/components/ui/Progress";
import Tabs from "@/components/ui/Tabs";
import { cn } from "@/lib/cn";
import {
  DEGREE_LABELS,
  KIND_ORDER,
  MATERIAL_KIND_LABELS,
  REVIEW_LABELS,
  STATUS_LABELS,
  STATUS_TONES,
  SUBJECT_ROLE_LABELS,
  fmtAdjust,
  fmtScore,
} from "./scholarshipModel";

const inputClass =
  "h-9 px-3 rounded-sm border border-outline-variant bg-surface-lowest text-body-sm text-on-surface outline-none focus:outline-2 focus:outline-primary";

function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n();
  return (
    <StatusChip tone={STATUS_TONES[status] ?? "neutral"}>
      {t(STATUS_LABELS[status] ?? status)}
    </StatusChip>
  );
}

/** 紧凑状态条：保留进度上下文，不让流程抢占资料阅读空间。 */
function StageBar({ status, pendingReputation }: { status: string; pendingReputation: number }) {
  const { t } = useI18n();
  const stages = [
    { key: "imported", label: t("已导入") },
    { key: "screened", label: t("已筛选") },
    { key: "scored", label: t("已评分") },
    { key: "reputed", label: t("舆情核验") },
    { key: "finalized", label: t("已定稿") },
  ];
  const reached: Record<string, boolean> = {
    imported: true,
    screened: ["eligible", "scored", "finalized"].includes(status),
    scored: ["scored", "finalized"].includes(status),
    reputed: ["scored", "finalized"].includes(status) && pendingReputation === 0,
    finalized: status === "finalized",
  };
  return (
    <div className="flex items-center gap-1 overflow-x-auto">
      {stages.map((s, i) => (
        <Fragment key={s.key}>
          {i > 0 && (
            <span className={cn("h-px flex-1 min-w-3", reached[s.key] ? "bg-primary" : "bg-outline-variant")} />
          )}
          <span
            className={cn(
              "shrink-0 flex items-center gap-1 text-label",
              reached[s.key] ? "text-primary" : "text-on-surface-variant",
            )}
          >
            <span
              className={cn(
                "size-4 rounded-full flex items-center justify-center",
                reached[s.key] ? "bg-primary text-on-primary" : "border border-outline-variant",
              )}
            >
              {reached[s.key] && <Icon name="check" size={11} />}
            </span>
            {s.label}
          </span>
        </Fragment>
      ))}
    </div>
  );
}

interface AddDialogProps {
  onClose: () => void;
  onDone: () => void;
}

/** 添加申请人：填表 → 传材料 → 自动筛选并展示结果（飞书来的申请不需要这个） */
function AddApplicantDialog({ onClose, onDone }: AddDialogProps) {
  const [step, setStep] = useState<"form" | "upload" | "result">("form");
  const [form, setForm] = useState({
    name: "", degree_type: "master", expected_graduation: "",
    direction: "", school: "", advisors: "",
  });
  const [created, setCreated] = useState<ScholarshipApplication | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [screenResult, setScreenResult] = useState<{ status: string; missing: string[]; reasons: string[] } | null>(null);
  const { t } = useI18n();

  const submitForm = async () => {
    if (!form.name.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const app = await api.scholarship.create({
        name: form.name.trim(),
        degree_type: form.degree_type,
        expected_graduation: form.expected_graduation.trim(),
        direction: form.direction.trim(),
        school: form.school.trim(),
        advisors: form.advisors.split(/[,，]/).map((s) => s.trim()).filter(Boolean),
      });
      setCreated(app);
      setStep("upload");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("创建失败"));
    } finally {
      setBusy(false);
    }
  };

  const uploadAndScreen = async (withFiles: boolean) => {
    if (!created || busy) return;
    setBusy(true);
    setError("");
    try {
      if (withFiles && files.length) await api.scholarship.uploadMaterials(created.id, files);
      setScreenResult(await api.scholarship.screen(created.id));
      setStep("result");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("操作失败"));
    } finally {
      setBusy(false);
    }
  };

  const close = () => { onDone(); onClose(); };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-inverse-surface/30" onClick={close}>
      <Card variant="elevated" className="w-[440px] p-5 flex flex-col gap-3" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <p className="text-title-lg">
            {step === "form" ? t("添加申请人") : step === "upload" ? t("上传申请材料") : t("筛选结果")}
          </p>
          <IconButton icon="close" onClick={close} title={t("关闭")} />
        </div>

        {step === "form" && (
          <>
            <input type="text" value={form.name} placeholder={t("姓名（必填）")} className={inputClass}
              onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))} />
            <select value={form.degree_type} className={cn(inputClass, "cursor-pointer")}
              onChange={(e) => setForm((p) => ({ ...p, degree_type: e.target.value }))}>
              <option value="master">{t("硕士")}</option>
              <option value="phd">{t("博士")}</option>
            </select>
            <input type="text" value={form.expected_graduation} placeholder={t("预计毕业时间（YYYY-MM）")} className={inputClass}
              onChange={(e) => setForm((p) => ({ ...p, expected_graduation: e.target.value }))} />
            <input type="text" value={form.direction} placeholder={t("研究方向")} className={inputClass}
              onChange={(e) => setForm((p) => ({ ...p, direction: e.target.value }))} />
            <input type="text" value={form.school} placeholder={t("学校")} className={inputClass}
              onChange={(e) => setForm((p) => ({ ...p, school: e.target.value }))} />
            <input type="text" value={form.advisors} placeholder={t("推荐导师（逗号分隔）")} className={inputClass}
              onChange={(e) => setForm((p) => ({ ...p, advisors: e.target.value }))} />
            <Button variant="filled" icon="arrow_forward" className="w-full" disabled={!form.name.trim() || busy} onClick={submitForm}>
              {busy ? t("创建中…") : t("下一步：上传材料")}
            </Button>
          </>
        )}

        {step === "upload" && (
          <>
            <p className="text-body-sm text-on-surface-variant">
              {t("为「{name}」上传材料：支持 zip 打包或多选散装文件，推荐信最多 2 封", { name: created?.name ?? "" })}
            </p>
            <input type="file" multiple className="text-body-sm text-on-surface-variant"
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
            {files.length > 0 && (
              <p className="text-label text-on-surface-variant">{t("已选 {n} 个文件", { n: files.length })}</p>
            )}
            <Button variant="filled" icon="upload" className="w-full" disabled={busy} onClick={() => uploadAndScreen(true)}>
              {busy ? t("处理中…") : files.length ? t("上传并筛选") : t("直接筛选")}
            </Button>
            <Button variant="text" className="w-full" disabled={busy} onClick={() => uploadAndScreen(false)}>
              {t("跳过上传，直接筛选")}
            </Button>
          </>
        )}

        {step === "result" && screenResult && (
          <>
            <div className="flex items-center gap-2">
              <span className="text-body-sm text-on-surface-variant">{created?.name}</span>
              <StatusBadge status={screenResult.status} />
            </div>
            {screenResult.missing.length > 0 && (
              <p className="text-body-sm text-warning">
                {t("缺少材料：")}{screenResult.missing.map((k) => t(MATERIAL_KIND_LABELS[k] ?? k)).join(t("、"))}
              </p>
            )}
            {screenResult.reasons.length > 0 && (
              <ul className="text-body-sm text-error list-disc pl-5">
                {screenResult.reasons.map((r) => <li key={r}>{r}</li>)}
              </ul>
            )}
            <Button variant="tonal" className="w-full" onClick={close}>{t("完成")}</Button>
          </>
        )}

        {error && <p className="text-label text-error">{error}</p>}
      </Card>
    </div>
  );
}

export type ScholarshipView = "overview" | "materials" | "assessment";
type AssessmentTab = "score" | "process" | "reputation";
const EMPTY_MATERIALS: ScholarshipMaterial[] = [];

export interface ScholarshipPaneProps {
  app: ScholarshipApplication | null;
  loading: boolean;
  missingSelection: boolean;
  view: ScholarshipView;
  onViewChange: (view: ScholarshipView) => void;
  onRefresh: () => void;
  onDeleted: () => void;
  addDialog: AddDialogProps | null;
}

function formatDate(value: string | null | undefined): string {
  return value ? value.slice(0, 16).replace("T", " ") : "—";
}

function materialIcon(filename: string): string {
  const name = filename.toLowerCase();
  if (name.endsWith(".pdf")) return "picture_as_pdf";
  if (/\.(png|jpe?g|gif|webp)$/i.test(name)) return "image";
  if (/\.(docx?|pages)$/i.test(name)) return "article";
  return "description";
}

function materialType(filename: string): string {
  const suffix = filename.split(".").pop()?.toUpperCase();
  return suffix && suffix.length <= 5 ? suffix : "FILE";
}

function InfoField({ icon, label, value, wide = false }: { icon: string; label: string; value: string; wide?: boolean }) {
  return (
    <div className={cn("min-w-0", wide && "sm:col-span-2")}>
      <dt className="flex items-center gap-1.5 text-label text-on-surface-variant">
        <Icon name={icon} size={15} />
        {label}
      </dt>
      <dd className="mt-1 truncate text-body-sm text-on-surface" title={value}>{value || "—"}</dd>
    </div>
  );
}

function MaterialExplorer({
  materials,
  groupedMaterials,
  compact = false,
}: {
  materials: ScholarshipMaterial[];
  groupedMaterials: [string, ScholarshipMaterial[]][];
  compact?: boolean;
}) {
  const { t } = useI18n();
  const [selectedId, setSelectedId] = useState<number | null>(materials[0]?.id ?? null);

  useEffect(() => {
    setSelectedId((current) => materials.some((material) => material.id === current) ? current : (materials[0]?.id ?? null));
  }, [materials]);

  const selected = materials.find((material) => material.id === selectedId) ?? null;

  return (
    <section className={cn(
      "min-h-0 overflow-hidden rounded-lg border border-outline-variant bg-surface-lowest flex flex-col",
      compact ? "h-full" : "flex-1",
    )}>
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-outline-variant px-4 py-3">
        <div className="min-w-0">
          <p className="text-title">{t("申请材料")}</p>
          <p className="mt-0.5 text-label text-on-surface-variant">{t("{n} 份材料 · 点击即可预览", { n: materials.length })}</p>
        </div>
        <Icon name="preview" size={19} className="text-on-surface-variant" />
      </div>

      <div className={cn(
        "grid min-h-0 flex-1",
        compact
          ? "grid-rows-[minmax(132px,0.42fr)_minmax(210px,0.58fr)]"
          : "grid-cols-1 md:grid-cols-[minmax(190px,0.38fr)_minmax(0,1fr)]",
      )}>
        <div className="min-h-0 overflow-y-auto border-b border-outline-variant md:border-b-0 md:border-r">
          {groupedMaterials.length === 0 ? (
            <div className="flex h-full min-h-36 flex-col items-center justify-center gap-2 px-4 text-center text-on-surface-variant">
              <Icon name="folder_open" size={26} />
              <p className="text-body-sm">{t("暂无材料")}</p>
            </div>
          ) : (
            <div className="p-2">
              {groupedMaterials.map(([kind, items]) => (
                <div key={kind} className="mb-2 last:mb-0">
                  <p className="px-2 py-1 text-label text-on-surface-variant">
                    {t(MATERIAL_KIND_LABELS[kind] ?? kind)} · {items.length}
                  </p>
                  <div className="flex flex-col gap-0.5">
                    {items.map((material) => {
                      const active = material.id === selectedId;
                      return (
                        <button
                          key={material.id}
                          type="button"
                          aria-pressed={active}
                          onClick={() => setSelectedId(material.id)}
                          className={cn(
                            "state-layer flex min-h-12 w-full items-center gap-2 rounded-md px-2 text-left transition-colors cursor-pointer",
                            active ? "bg-primary-container text-on-primary-container" : "text-on-surface hover:bg-surface-low",
                          )}
                        >
                          <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-md", active ? "bg-surface-lowest/70" : "bg-surface-low")}>
                            <Icon name={materialIcon(material.filename)} size={17} />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-body-sm">{material.filename}</span>
                            <span className="mt-0.5 block text-label opacity-70">
                              {materialType(material.filename)} · {material.raw_text ? t("已解析") : t("待解析")}
                            </span>
                          </span>
                          {active && <Icon name="chevron_right" size={16} className="shrink-0" />}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="flex min-h-0 flex-col bg-surface">
          {selected ? (
            <>
              <div className="flex shrink-0 items-center gap-3 border-b border-outline-variant px-4 py-3">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-secondary-container text-on-secondary-container">
                  <Icon name={materialIcon(selected.filename)} size={17} />
                </span>
                <div className="min-w-0">
                  <p className="truncate text-body-sm font-medium text-on-surface">{selected.filename}</p>
                  <p className="mt-0.5 text-label text-on-surface-variant">
                    {materialType(selected.filename)} · {t(MATERIAL_KIND_LABELS[selected.kind] ?? selected.kind)}
                    {selected.advisor_name ? ` · ${selected.advisor_name}` : ""}
                  </p>
                </div>
              </div>
              <div className="scholarship-preview-scroll min-h-0 flex-1 overflow-y-auto p-4">
                {selected.raw_text ? (
                  <div className="min-h-full rounded-md border border-outline-variant bg-surface-lowest p-4">
                    <pre className="whitespace-pre-wrap break-words text-body-sm leading-6 text-on-surface">{selected.raw_text}</pre>
                  </div>
                ) : (
                  <div className="flex h-full min-h-40 flex-col items-center justify-center gap-2 rounded-md border border-dashed border-outline-variant px-5 text-center text-on-surface-variant">
                    <Icon name="visibility_off" size={26} />
                    <p className="text-body-sm">{t("当前文件暂无可预览文本")}</p>
                    <p className="text-label">{t("解析完成后会在这里即时展示内容")}</p>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center gap-2 px-5 text-center text-on-surface-variant">
              <Icon name="preview" size={30} />
              <p className="text-body-sm">{t("选择一份材料开始预览")}</p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function ScoreMetric({ label, value, tone = "default" }: { label: string; value: string; tone?: "default" | "primary" | "warning" }) {
  return (
    <div className="rounded-lg border border-outline-variant bg-surface-lowest px-4 py-3">
      <p className="text-label text-on-surface-variant">{label}</p>
      <p className={cn(
        "mt-1 font-mono text-title-lg tabular-nums",
        tone === "primary" && "text-primary",
        tone === "warning" && "text-warning",
      )}>{value}</p>
    </div>
  );
}

function TraceStatus({ status }: { status: "completed" | "running" | "failed" | "pending" }) {
  const icon = status === "completed" ? "check" : status === "running" ? "progress_activity" : status === "failed" ? "error" : "radio_button_unchecked";
  const tone = status === "completed" ? "bg-success text-on-primary" : status === "running" ? "bg-primary text-on-primary" : status === "failed" ? "bg-error text-on-error" : "bg-surface-high text-on-surface-variant";
  return <span className={cn("flex size-7 shrink-0 items-center justify-center rounded-full", tone)}><Icon name={icon} size={15} /></span>;
}

export default function ScholarshipPane({
  app, loading, missingSelection, view, onViewChange, onRefresh, onDeleted, addDialog,
}: ScholarshipPaneProps) {
  const { t } = useI18n();
  const [error, setError] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [reviewing, setReviewing] = useState<Record<number, boolean>>({});
  const [assessmentTab, setAssessmentTab] = useState<AssessmentTab>("score");

  const latestCompleted = useMemo(
    () => [...(app?.evaluations ?? [])].reverse().find((e) => e.status === "completed"),
    [app],
  );
  const latestEval = app?.evaluations?.[app.evaluations.length - 1];
  const materials = app?.materials ?? EMPTY_MATERIALS;
  const groupedMaterials = useMemo(() => {
    const groups = new Map<string, ScholarshipMaterial[]>();
    for (const material of materials) {
      const list = groups.get(material.kind) ?? [];
      list.push(material);
      groups.set(material.kind, list);
    }
    return [...groups.entries()].sort((a, b) => (KIND_ORDER.indexOf(a[0]) + 99) - (KIND_ORDER.indexOf(b[0]) + 99));
  }, [materials]);

  useEffect(() => {
    setAssessmentTab("score");
    setError("");
    setConfirmingDelete(false);
  }, [app?.id]);

  const runAction = async (action: string, fn: () => Promise<void>) => {
    if (busyAction) return;
    setBusyAction(action);
    setError("");
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("操作失败"));
    } finally {
      setBusyAction("");
    }
  };

  const handleEvaluate = () =>
    runAction("evaluate", async () => {
      await api.scholarship.evaluate(app!.id);
      for (let i = 0; i < 30; i++) {
        const detail = await api.scholarship.get(app!.id);
        const latest = detail.evaluations?.[detail.evaluations.length - 1];
        if (!latest || latest.status !== "running") break;
        await new Promise((resolve) => setTimeout(resolve, 2000));
      }
      onRefresh();
    });

  const review = async (itemId: number, action: "confirmed" | "dismissed") => {
    if (reviewing[itemId]) return;
    setReviewing((previous) => ({ ...previous, [itemId]: true }));
    setError("");
    try {
      await api.scholarship.reviewReputation(itemId, action);
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("操作失败"));
    } finally {
      setReviewing((previous) => ({ ...previous, [itemId]: false }));
    }
  };

  if (addDialog) {
    return (
      <>
        <AddApplicantDialog onClose={addDialog.onClose} onDone={addDialog.onDone} />
        <Body />
      </>
    );
  }
  return <Body />;

  function Body() {
    if (missingSelection || !app) {
      return (
        <Card variant="filled" className="min-h-0 flex-1 min-w-0 overflow-hidden flex flex-col">
          <div className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-on-surface-variant">
            {loading ? <><LoadingIndicator size={28} /><p className="text-body-sm">{t("加载中…")}</p></> : <><Icon name="badge" size={32} /><p className="text-body-sm">{t("从左侧选择一位申请人查看详情")}</p></>}
          </div>
        </Card>
      );
    }

    const acting = busyAction;
    const canEvaluate = !["imported", "material_incomplete", "ineligible"].includes(app.status);
    const pendingReputation = app.pending_reputation;
    const reputationItems = app.reputation_items ?? [];

    return (
      <Card variant="filled" className="min-h-0 flex-1 min-w-0 overflow-hidden flex flex-col">
        <div className="shrink-0 border-b border-outline-variant px-5 py-4">
          <div className="flex items-start gap-3">
            <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary-container text-title text-on-primary-container">
              {(app.name || t("未命名")).charAt(0)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="truncate text-headline leading-tight">{app.name || t("未命名")}</h1>
                <StatusBadge status={app.status} />
                {app.feishu_record_id && <span className="inline-flex items-center gap-1 text-label text-on-surface-variant"><Icon name="cloud_done" size={13} />{t("飞书同步")}</span>}
              </div>
              <p className="mt-1 truncate text-body-sm text-on-surface-variant">
                {[app.name_en, app.school, app.lab, app.degree_type ? t(DEGREE_LABELS[app.degree_type] ?? app.degree_type) : "", app.grade, app.expected_graduation].filter(Boolean).join(" · ") || "—"}
              </p>
              <p className="mt-0.5 truncate text-label text-on-surface-variant">
                {[app.direction, app.advisors?.length ? `${t("导师")}：${app.advisors.join(t("、"))}` : "", app.email].filter(Boolean).join(" · ") || "—"}
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
              {view === "assessment" ? (
                <>
                  <Button variant="outlined" icon="fact_check" className="h-8 px-3" disabled={!!acting} onClick={() => runAction("screen", async () => { await api.scholarship.screen(app.id); onRefresh(); })}>{t("重新筛选")}</Button>
                  <Button variant="tonal" icon="grade" className="h-8 px-3" disabled={!!acting || !canEvaluate} onClick={handleEvaluate}>{t("开始评估")}</Button>
                  <Button variant="text" icon="travel_explore" className="h-8 px-3" disabled={!!acting} onClick={() => runAction("scan", async () => { await api.scholarship.reputationScan(app.id); onRefresh(); })}>{t("舆情扫描")}</Button>
                </>
              ) : (
                <Button variant="tonal" icon="fact_check" className="h-8 px-3" onClick={() => onViewChange("assessment")}>{t("评估与核验")}</Button>
              )}
              {confirmingDelete ? (
                <>
                  <span className="text-label text-error">{t("确认删除？")}</span>
                  <IconButton icon="check" size={16} className="h-8 w-8" title={t("确认")} onClick={() => runAction("delete", async () => { await api.scholarship.remove(app.id); onDeleted(); })} />
                  <IconButton icon="close" size={16} className="h-8 w-8" title={t("取消")} onClick={() => setConfirmingDelete(false)} />
                </>
              ) : <IconButton icon="delete" size={18} title={t("删除")} disabled={!!acting} onClick={() => setConfirmingDelete(true)} />}
            </div>
          </div>
          <div className="mt-4 flex items-center gap-3 rounded-md bg-surface-low px-3 py-2.5">
            <span className="shrink-0 text-label font-medium text-on-surface-variant">{t("申请进度")}</span>
            <div className="min-w-0 flex-1"><StageBar status={app.status} pendingReputation={pendingReputation} /></div>
          </div>
          {acting && <div className="mt-2 inline-flex items-center gap-1.5 text-label text-on-surface-variant"><LoadingIndicator size={13} />{acting === "evaluate" ? t("评估中…") : acting === "screen" ? t("筛选中…") : acting === "scan" ? t("扫描中…") : t("删除中…")}</div>}
          {error && <p className="mt-2 text-body-sm text-error">{error}</p>}
        </div>

        {view === "assessment" && (
          <Tabs
            value={assessmentTab}
            onChange={setAssessmentTab}
            className="shrink-0 px-2"
            items={[
              { value: "score", label: t("评分结果"), badge: latestCompleted ? "✓" : undefined },
              { value: "process", label: t("评估过程") },
              { value: "reputation", label: t("舆情核验"), badge: pendingReputation || undefined },
            ]}
          />
        )}

        {view === "overview" && (
          <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.62fr)]">
            <div className="min-h-0 overflow-y-auto px-5 py-4">
              {(app.status === "material_incomplete" || app.status === "ineligible") && (
                <section className="mb-5 rounded-lg border border-warning/40 bg-warning-container/40 px-4 py-3">
                  <div className="flex items-center gap-2 text-body-sm font-medium text-warning"><Icon name="warning" size={17} />{t("筛选需要处理")}</div>
                  {(app.screening_detail?.missing ?? []).length > 0 && <p className="mt-1 text-body-sm text-on-surface">{t("缺少材料：")}{(app.screening_detail.missing ?? []).map((kind) => t(MATERIAL_KIND_LABELS[kind] ?? kind)).join(t("、"))}</p>}
                  {(app.screening_detail?.reasons ?? []).map((reason) => <p key={reason} className="mt-1 text-body-sm text-error">{reason}</p>)}
                </section>
              )}

              <section className="border-b border-outline-variant pb-5">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-title-lg">{t("研究方向简述")}</h2>
                  <span className="text-label text-on-surface-variant">{t("申请人自述")}</span>
                </div>
                <p className="mt-3 max-h-32 overflow-y-auto border-l-2 border-primary-container pl-3 text-body-sm leading-6 text-on-surface whitespace-pre-wrap">
                  {app.research_summary || t("暂无研究方向简述")}
                </p>
              </section>

              <section className="border-b border-outline-variant py-5">
                <h2 className="text-title-lg">{t("关键资料")}</h2>
                <dl className="mt-4 grid grid-cols-1 gap-x-5 gap-y-4 sm:grid-cols-2">
                  <InfoField icon="school" label={t("学校")} value={app.school} />
                  <InfoField icon="science" label={t("实验室")} value={app.lab} />
                  <InfoField icon="explore" label={t("研究方向")} value={app.direction} />
                  <InfoField icon="school" label={t("学位与年级")} value={[app.degree_type ? t(DEGREE_LABELS[app.degree_type] ?? app.degree_type) : "", app.grade].filter(Boolean).join(" · ")} />
                  <InfoField icon="event" label={t("预计毕业")} value={app.expected_graduation} />
                  <InfoField icon="cloud_done" label={t("申请来源")} value={app.feishu_record_id ? t("飞书问卷") : t("手动添加")} />
                  <InfoField icon="person" label={t("导师")} value={app.advisors?.join(t("、")) || "—"} wide />
                </dl>
              </section>

              <section className="border-b border-outline-variant py-5">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-title-lg">{t("教育与科研经历")}</h2>
                  {app.submitted_at && <span className="text-label text-on-surface-variant">{t("提交于 {v}", { v: formatDate(app.submitted_at) })}</span>}
                </div>
                <p className="mt-3 max-h-40 overflow-y-auto whitespace-pre-wrap text-body-sm leading-6 text-on-surface">
                  {app.education_history || t("暂无教育与科研经历")}
                </p>
              </section>

              <section className="pt-5">
                <h2 className="text-title-lg">{t("联系方式")}</h2>
                <dl className="mt-4 grid grid-cols-1 gap-x-5 gap-y-4 sm:grid-cols-2">
                  <InfoField icon="mail" label={t("邮箱")} value={app.email} />
                  <InfoField icon="phone" label={t("电话")} value={app.phone} />
                  <InfoField icon="public" label={t("所在地区")} value={app.country} />
                  <InfoField icon="schedule" label={t("材料数量")} value={t("{n} 份", { n: materials.length })} />
                </dl>
              </section>
            </div>
            <div className="min-h-0 border-t border-outline-variant p-4 lg:border-l lg:border-t-0">
              <MaterialExplorer materials={materials} groupedMaterials={groupedMaterials} compact />
            </div>
          </div>
        )}

        {view === "materials" && (
          <div className="flex min-h-0 flex-1 p-4"><MaterialExplorer materials={materials} groupedMaterials={groupedMaterials} /></div>
        )}

        {view === "assessment" && (
          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
            {assessmentTab === "score" && (
              <div className="flex flex-col gap-5">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1.2fr_repeat(2,minmax(0,1fr))]">
                  <div className="rounded-lg bg-primary px-4 py-3 text-on-primary">
                    <p className="text-label opacity-75">{t("当前总分")}</p>
                    <p className="mt-1 font-mono text-display leading-none tabular-nums">{fmtScore(app.total_score)}</p>
                    <p className="mt-2 text-label opacity-75">{t("脱敏分 + 舆情调整")}</p>
                  </div>
                  <ScoreMetric label={t("脱敏分")} value={fmtScore(app.blind_score)} />
                  <ScoreMetric label={t("舆情调整")} value={fmtAdjust(app.reputation_adjustment)} tone={app.reputation_adjustment < 0 ? "warning" : "default"} />
                </div>
                <div className="flex items-center justify-between gap-3">
                  <div><h2 className="text-title-lg">{t("评分明细")}</h2><p className="mt-0.5 text-label text-on-surface-variant">{latestCompleted ? `${latestCompleted.config_version} · ${formatDate(latestCompleted.created_at)}` : t("尚未生成评分结果")}</p></div>
                  <StatusChip tone={latestEval?.status === "failed" ? "error" : latestCompleted ? "success" : "neutral"}>{latestEval?.status === "running" ? t("评估中…") : latestEval?.status === "failed" ? t("评估失败") : latestCompleted ? t("已完成") : t("未开始")}</StatusChip>
                </div>
                {latestEval?.status === "running" ? <div className="rounded-lg border border-outline-variant px-4 py-6"><LoadingIndicator size={20} label={t("评估中…")} /></div> : latestEval?.status === "failed" ? <p className="rounded-lg border border-error/40 bg-error-container px-4 py-3 text-body-sm text-error">{t("评估失败：{msg}", { msg: latestEval.error_message || t("未知错误") })}</p> : !latestCompleted ? <p className="rounded-lg border border-dashed border-outline-variant px-4 py-6 text-body-sm text-on-surface-variant">{t("暂无评估结果，点上方「开始评估」生成")}</p> : (
                  <>
                    <div className="grid grid-cols-1 gap-2 lg:grid-cols-2">
                      {latestCompleted.dimensions.map((dimension) => (
                        <div key={dimension.key} className="rounded-lg border border-outline-variant px-4 py-3">
                          <div className="flex items-center justify-between gap-3"><span className="text-body-sm font-medium text-on-surface">{dimension.label}</span><span className="font-mono text-label tabular-nums text-on-surface-variant">{dimension.score}/5 · {dimension.max_points}</span></div>
                          <Progress value={(dimension.score / 5) * 100} className="my-2" />
                          {dimension.reason && <p className="text-label leading-5 text-on-surface-variant">{dimension.reason}</p>}
                        </div>
                      ))}
                    </div>
                    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                      <div><p className="mb-2 text-label text-on-surface-variant">{t("亮点")}</p><ul className="flex flex-col gap-1.5">{latestCompleted.highlights.map((highlight) => <li key={highlight} className="flex items-start gap-2 text-body-sm"><Icon name="check_circle" size={16} className="mt-0.5 shrink-0 text-success" />{highlight}</li>)}{!latestCompleted.highlights.length && <li className="text-body-sm text-on-surface-variant">—</li>}</ul></div>
                      <div><p className="mb-2 text-label text-on-surface-variant">{t("风险")}</p><ul className="flex flex-col gap-1.5">{latestCompleted.risks.map((risk) => <li key={risk} className="flex items-start gap-2 text-body-sm"><Icon name="warning" size={16} className="mt-0.5 shrink-0 text-warning" />{risk}</li>)}{!latestCompleted.risks.length && <li className="text-body-sm text-on-surface-variant">—</li>}</ul></div>
                    </div>
                  </>
                )}
              </div>
            )}

            {assessmentTab === "process" && (
              <div className="max-w-3xl">
                <div className="mb-5"><h2 className="text-title-lg">{t("评估过程")}</h2><p className="mt-1 text-body-sm text-on-surface-variant">{t("查看本次评估的实际状态与结果")}</p></div>
                <div className="flex flex-col">
                  {[
                    { label: t("评估任务"), detail: latestEval ? t("已创建评估记录") : t("尚未发起评估"), status: latestEval?.status === "running" ? "running" : latestEval?.status === "failed" ? "failed" : latestEval ? "completed" : "pending" },
                    { label: t("评分结果"), detail: latestCompleted ? t("已生成各维度评分与依据") : t("等待评估完成"), status: latestCompleted ? "completed" : latestEval?.status === "failed" ? "failed" : "pending" },
                    { label: t("总分汇总"), detail: app.total_score != null ? t("已按脱敏分与舆情调整汇总") : t("等待评分结果"), status: app.total_score != null ? "completed" : "pending" },
                    { label: t("人工核验"), detail: pendingReputation ? t("{n} 条舆情待核验", { n: pendingReputation }) : reputationItems.length ? t("舆情条目已处理") : t("尚未发起舆情扫描"), status: pendingReputation ? "running" : reputationItems.length ? "completed" : "pending" },
                  ].map((step, index, steps) => (
                    <div key={step.label} className="relative flex gap-3 pb-6 last:pb-0">
                      {index < steps.length - 1 && <span className="absolute left-3.5 top-8 bottom-0 w-px bg-outline-variant" />}
                      <TraceStatus status={step.status as "completed" | "running" | "failed" | "pending"} />
                      <div className="min-w-0 flex-1"><div className="flex items-center justify-between gap-3"><p className="text-body-sm font-medium text-on-surface">{step.label}</p><span className="text-label text-on-surface-variant">{step.status === "completed" ? t("已完成") : step.status === "running" ? t("处理中") : step.status === "failed" ? t("失败") : t("未开始")}</span></div><p className="mt-1 text-label leading-5 text-on-surface-variant">{step.detail}</p></div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {assessmentTab === "reputation" && (
              <div className="flex flex-col gap-4">
                <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-title-lg">{t("舆情核验")}</h2><p className="mt-1 text-body-sm text-on-surface-variant">{t("只对扫描结果进行人工确认，不改变申请资料")}</p></div><span className="text-label text-warning">{t("{n} 条待人工核验", { n: pendingReputation })}</span></div>
                {reputationItems.length === 0 ? <div className="rounded-lg border border-dashed border-outline-variant px-4 py-8 text-body-sm text-on-surface-variant">{t("暂无舆情条目，点上方「舆情扫描」发起")}</div> : <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">{reputationItems.map((item) => <div key={item.id} className="rounded-lg border border-outline-variant px-4 py-3"><div className="flex flex-wrap items-center gap-2"><span className="text-body-sm font-medium">{item.subject}</span><span className="text-label text-on-surface-variant">{t(SUBJECT_ROLE_LABELS[item.subject_role] ?? item.subject_role)}</span><StatusChip tone={item.sentiment === "negative" ? "error" : "success"} variant={item.sentiment === "negative" ? "filled" : "dot"}>{item.sentiment === "negative" ? t("负面") : t("正面")}</StatusChip>{item.review_status !== "pending" && <StatusChip tone={item.review_status === "confirmed" ? "warning" : "neutral"}>{t(REVIEW_LABELS[item.review_status] ?? item.review_status)} {fmtAdjust(item.adjustment)}</StatusChip>}</div><a href={item.url} target="_blank" rel="noreferrer" className="mt-2 block text-body-sm text-primary hover:underline">{item.title || item.url}</a>{item.snippet && <p className="mt-1 text-label leading-5 text-on-surface-variant">{item.snippet}</p>}{item.concern && <p className="mt-2 text-body-sm text-error">{t("风险点：{concern}", { concern: item.concern })}</p>}{item.review_status === "pending" && <div className="mt-3 flex items-center gap-2"><Button variant="tonal" icon="check" className="h-8 px-3" disabled={reviewing[item.id]} onClick={() => review(item.id, "confirmed")}>{t("确认")}</Button><Button variant="outlined" icon="close" className="h-8 px-3" disabled={reviewing[item.id]} onClick={() => review(item.id, "dismissed")}>{t("驳回")}</Button></div>}</div>)}</div>}
              </div>
            )}
          </div>
        )}
      </Card>
    );
  }
}
