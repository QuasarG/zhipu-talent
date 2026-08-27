// 奖学金右栏：申请人信息 / 评估链路操作 / 材料分组 / 评分明细 / 舆情核验 / 品牌加分
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

/** 链路步骤条：导入 → 筛选 → 盲评 → 舆情 → 定稿（据当前状态点亮） */
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

export interface ScholarshipPaneProps {
  app: ScholarshipApplication | null;
  loading: boolean;
  missingSelection: boolean;
  onRefresh: () => void;
  onDeleted: () => void;
  addDialog: AddDialogProps | null;
}

export default function ScholarshipPane({
  app, loading, missingSelection, onRefresh, onDeleted, addDialog,
}: ScholarshipPaneProps) {
  const { t } = useI18n();
  const [error, setError] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [brandBonus, setBrandBonus] = useState("0");
  const [brandNote, setBrandNote] = useState("");
  const [savingBrand, setSavingBrand] = useState(false);
  const [reviewing, setReviewing] = useState<Record<number, boolean>>({});

  // 品牌加编辑入框跟随详情
  useEffect(() => {
    if (app) {
      setBrandBonus(String(app.brand_bonus ?? 0));
      setBrandNote(app.brand_note ?? "");
    }
  }, [app?.id, app?.brand_bonus, app?.brand_note]); // eslint-disable-line react-hooks/exhaustive-deps

  const latestCompleted = useMemo(
    () => [...(app?.evaluations ?? [])].reverse().find((e) => e.status === "completed"),
    [app],
  );
  const latestEval = app?.evaluations?.[app.evaluations.length - 1];

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
      // 评估接口同步阻塞返回，轮询兜底确认不再 running
      for (let i = 0; i < 30; i++) {
        const d = await api.scholarship.get(app!.id);
        const latest = d.evaluations?.[d.evaluations.length - 1];
        if (!latest || latest.status !== "running") break;
        await new Promise((r) => setTimeout(r, 2000));
      }
      onRefresh();
    });

  const saveBrand = async () => {
    if (!app || savingBrand) return;
    const bonus = Number(brandBonus);
    if (Number.isNaN(bonus)) {
      setError(t("品牌加分必须是数字"));
      return;
    }
    setSavingBrand(true);
    setError("");
    try {
      await api.scholarship.setBrand(app.id, bonus, brandNote.trim());
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("保存失败"));
    } finally {
      setSavingBrand(false);
    }
  };

  const review = async (itemId: number, action: "confirmed" | "dismissed") => {
    if (reviewing[itemId]) return;
    setReviewing((p) => ({ ...p, [itemId]: true }));
    setError("");
    try {
      await api.scholarship.reviewReputation(itemId, action);
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("操作失败"));
    } finally {
      setReviewing((p) => ({ ...p, [itemId]: false }));
    }
  };

  const groupedMaterials = useMemo(() => {
    const groups = new Map<string, ScholarshipMaterial[]>();
    for (const m of app?.materials ?? []) {
      const list = groups.get(m.kind) ?? [];
      list.push(m);
      groups.set(m.kind, list);
    }
    return [...groups.entries()].sort(
      (a, b) => (KIND_ORDER.indexOf(a[0]) + 99) - (KIND_ORDER.indexOf(b[0]) + 99),
    );
  }, [app]);

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
          <div className="flex flex-1 flex-col items-center justify-center gap-3 text-on-surface-variant px-6">
            {loading ? (
              <>
                <LoadingIndicator size={28} />
                <p className="text-body-sm">{t("加载中…")}</p>
              </>
            ) : (
              <>
                <Icon name="badge" size={32} />
                <p className="text-body-sm">{t("从左侧选择一位申请人查看详情")}</p>
              </>
            )}
          </div>
        </Card>
      );
    }

    const acting = busyAction;
    return (
      <Card variant="filled" className="min-h-0 flex-1 min-w-0 overflow-y-auto p-4 flex flex-col gap-4">
        {/* 头部：姓名 + 状态 + 主操作 */}
        <div className="flex items-start gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-headline leading-tight truncate">{app.name || t("未命名")}</h1>
              <StatusBadge status={app.status} />
              {app.feishu_record_id && (
                <span className="text-label text-on-surface-variant flex items-center gap-1">
                  <Icon name="cloud_done" size={13} />
                  {t("飞书同步")}
                </span>
              )}
            </div>
            <p className="text-body-sm text-on-surface-variant mt-1">
              {[
                app.name_en,
                app.school,
                app.lab,
                app.degree_type ? t(DEGREE_LABELS[app.degree_type] ?? app.degree_type) : "",
                app.grade,
                app.expected_graduation,
              ].filter(Boolean).join(" · ") || "—"}
            </p>
            {app.advisors.length > 0 && (
              <p className="text-body-sm text-on-surface-variant mt-0.5">
                {t("推荐导师：{advisors}", { advisors: app.advisors.join(t("、")) })}
                {app.advisor_title && ` · ${app.advisor_title}`}
              </p>
            )}
            {(app.phone || app.email || app.country) && (
              <p className="text-label text-on-surface-variant mt-0.5">
                {[app.country, app.phone, app.email].filter(Boolean).join(" · ")}
              </p>
            )}
          </div>
          <div className="shrink-0 flex flex-col items-end gap-2">
            <div className="flex items-center gap-1">
              <IconButton icon="fact_check" size={18} title={t("筛选")} disabled={!!acting}
                onClick={() => runAction("screen", async () => { await api.scholarship.screen(app.id); onRefresh(); })} />
              <IconButton icon="grade" size={18} title={t("评估")} disabled={!!acting || app.status === "imported" || app.status === "material_incomplete" || app.status === "ineligible"}
                onClick={handleEvaluate} />
              <IconButton icon="travel_explore" size={18} title={t("舆情扫描")} disabled={!!acting}
                onClick={() => runAction("scan", async () => { await api.scholarship.reputationScan(app.id); onRefresh(); })} />
              {confirmingDelete ? (
                <>
                  <span className="text-label text-error mr-1">{t("确认删除？")}</span>
                  <IconButton icon="check" size={16} className="w-8 h-8" title={t("确认")}
                    onClick={() => runAction("delete", async () => { await api.scholarship.remove(app.id); onDeleted(); })} />
                  <IconButton icon="close" size={16} className="w-8 h-8" title={t("取消")}
                    onClick={() => setConfirmingDelete(false)} />
                </>
              ) : (
                <IconButton icon="delete" size={18} title={t("删除")} disabled={!!acting}
                  onClick={() => setConfirmingDelete(true)} />
              )}
            </div>
            {acting && (
              <span className="inline-flex items-center gap-1.5 text-label text-on-surface-variant">
                <LoadingIndicator size={13} />
                {acting === "evaluate" ? t("评估中…") : acting === "screen" ? t("筛选中…") : acting === "scan" ? t("扫描中…") : t("删除中…")}
              </span>
            )}
          </div>
        </div>

        {error && <p className="text-body-sm text-error">{error}</p>}

        {/* 筛选结论 */}
        {(app.status === "material_incomplete" || app.status === "ineligible") && (
          <div className="rounded-md border border-outline-variant px-3 py-2 flex flex-col gap-1">
            {(app.screening_detail?.missing ?? []).length > 0 && (
              <p className="text-body-sm text-warning">
                {t("缺少材料：")}{(app.screening_detail.missing ?? []).map((k) => t(MATERIAL_KIND_LABELS[k] ?? k)).join(t("、"))}
              </p>
            )}
            {(app.screening_detail?.reasons ?? []).map((r) => (
              <p key={r} className="text-body-sm text-error">{r}</p>
            ))}
          </div>
        )}

        {/* 链路进度 */}
        <div className="rounded-md border border-outline-variant px-4 py-3">
          <StageBar status={app.status} pendingReputation={app.pending_reputation} />
        </div>

        {/* 三个分数卡 */}
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-md border border-outline-variant p-3">
            <p className="text-label text-on-surface-variant">{t("脱敏分")}</p>
            <p className="text-headline mt-0.5">{fmtScore(app.blind_score)}</p>
          </div>
          <div className="rounded-md border border-outline-variant p-3">
            <p className="text-label text-on-surface-variant">{t("舆情调整")}</p>
            <p className={cn("text-headline mt-0.5", app.reputation_adjustment < 0 && "text-error")}>
              {fmtAdjust(app.reputation_adjustment)}
            </p>
          </div>
          <div className="rounded-md border border-outline-variant p-3">
            <p className="text-label text-on-surface-variant">{t("总分")}</p>
            <p className="text-headline mt-0.5 text-primary">{fmtScore(app.total_score)}</p>
          </div>
        </div>

        {/* 评分明细 */}
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <p className="text-title-lg">{t("评分明细")}</p>
            {latestCompleted && (
              <span className="text-label text-on-surface-variant">
                {latestCompleted.config_version} · {latestCompleted.created_at?.slice(0, 16).replace("T", " ")}
              </span>
            )}
          </div>
          {latestEval?.status === "running" ? (
            <LoadingIndicator size={20} label={t("评估中…")} />
          ) : latestEval?.status === "failed" ? (
            <p className="text-body-sm text-error">{t("评估失败：{msg}", { msg: latestEval.error_message || t("未知错误") })}</p>
          ) : !latestCompleted ? (
            <p className="text-body-sm text-on-surface-variant">{t("暂无评估结果，点上方「评估」开始盲评")}</p>
          ) : (
            <>
              <div className="flex flex-col gap-3">
                {latestCompleted.dimensions.map((d) => (
                  <div key={d.key} className="flex flex-col gap-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-body-sm text-on-surface">{d.label}</span>
                      <span className="text-label text-on-surface-variant shrink-0">
                        {t("{score}/5 · {max} 分权重", { score: d.score, max: d.max_points })}
                      </span>
                    </div>
                    <Progress value={(d.score / 5) * 100} />
                    {d.reason && <p className="text-label text-on-surface-variant">{d.reason}</p>}
                  </div>
                ))}
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <p className="text-label text-on-surface-variant mb-1.5">{t("亮点")}</p>
                  <ul className="flex flex-col gap-1">
                    {latestCompleted.highlights.map((h) => (
                      <li key={h} className="flex items-start gap-1.5 text-body-sm text-on-surface">
                        <Icon name="check_circle" size={16} className="text-success shrink-0 mt-0.5" />
                        {h}
                      </li>
                    ))}
                    {latestCompleted.highlights.length === 0 && <li className="text-body-sm text-on-surface-variant">—</li>}
                  </ul>
                </div>
                <div>
                  <p className="text-label text-on-surface-variant mb-1.5">{t("风险")}</p>
                  <ul className="flex flex-col gap-1">
                    {latestCompleted.risks.map((r) => (
                      <li key={r} className="flex items-start gap-1.5 text-body-sm text-on-surface">
                        <Icon name="warning" size={16} className="text-warning shrink-0 mt-0.5" />
                        {r}
                      </li>
                    ))}
                    {latestCompleted.risks.length === 0 && <li className="text-body-sm text-on-surface-variant">—</li>}
                  </ul>
                </div>
              </div>
            </>
          )}
        </div>

        {/* 舆情核验 */}
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <p className="text-title-lg">{t("舆情核验")}</p>
            {app.pending_reputation > 0 && (
              <span className="text-label text-warning">{t("{n} 条待人工核验", { n: app.pending_reputation })}</span>
            )}
          </div>
          {(app.reputation_items ?? []).length === 0 ? (
            <p className="text-body-sm text-on-surface-variant">{t("暂无舆情条目，点上方「舆情扫描」发起")}</p>
          ) : (
            <div className="flex flex-col gap-2">
              {(app.reputation_items ?? []).map((item) => (
                <div key={item.id} className="border border-outline-variant rounded-lg p-3 flex flex-col gap-1.5">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-body-sm font-medium text-on-surface">
                      {item.subject}
                      <span className="ml-1 text-label text-on-surface-variant">
                        {t(SUBJECT_ROLE_LABELS[item.subject_role] ?? item.subject_role)}
                      </span>
                    </span>
                    <StatusChip
                      tone={item.sentiment === "negative" ? "error" : "success"}
                      variant={item.sentiment === "negative" ? "filled" : "dot"}
                    >
                      {item.sentiment === "negative" ? t("负面") : t("正面")}
                    </StatusChip>
                    {item.review_status !== "pending" && (
                      <StatusChip tone={item.review_status === "confirmed" ? "warning" : "neutral"}>
                        {t(REVIEW_LABELS[item.review_status] ?? item.review_status)} {fmtAdjust(item.adjustment)}
                      </StatusChip>
                    )}
                  </div>
                  <a href={item.url} target="_blank" rel="noreferrer" className="text-body-sm text-primary hover:underline">
                    {item.title || item.url}
                  </a>
                  {item.snippet && <p className="text-label text-on-surface-variant">{item.snippet}</p>}
                  {item.concern && <p className="text-body-sm text-error">{t("风险点：{concern}", { concern: item.concern })}</p>}
                  {item.review_status === "pending" && (
                    <div className="flex items-center gap-2 mt-1">
                      <Button variant="tonal" icon="check" className="h-8 px-4" disabled={reviewing[item.id]}
                        onClick={() => review(item.id, "confirmed")}>{t("确认")}</Button>
                      <Button variant="outlined" icon="close" className="h-8 px-4" disabled={reviewing[item.id]}
                        onClick={() => review(item.id, "dismissed")}>{t("驳回")}</Button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 品牌加分 */}
        <div className="flex flex-col gap-3">
          <p className="text-title-lg">{t("品牌加分")}</p>
          <div className="flex items-center gap-2 flex-wrap">
            <input type="number" step="0.5" min="-10" max="10" value={brandBonus}
              onChange={(e) => setBrandBonus(e.target.value)} className={cn(inputClass, "w-24")}
              placeholder={t("加分")} />
            <input type="text" value={brandNote}
              onChange={(e) => setBrandNote(e.target.value)} className={cn(inputClass, "flex-1 min-w-48")}
              placeholder={t("备注（如：目标院校品牌）")} />
            <Button variant="tonal" icon="save" disabled={savingBrand} onClick={saveBrand}>
              {savingBrand ? t("保存中…") : t("保存")}
            </Button>
          </div>
          {app.brand_note && (
            <p className="text-label text-on-surface-variant">
              {t("当前：{v} 分 · {note}", { v: fmtAdjust(app.brand_bonus), note: app.brand_note })}
            </p>
          )}
        </div>

        {/* 飞书问卷补充信息 */}
        {(app.research_summary || app.education_history) && (
          <div className="flex flex-col gap-3">
            <p className="text-title-lg">{t("问卷补充信息")}</p>
            {app.research_summary && (
              <div className="rounded-md border border-outline-variant px-3 py-2">
                <p className="text-label text-on-surface-variant mb-1">{t("研究方向简述")}</p>
                <p className="text-body-sm text-on-surface whitespace-pre-wrap">{app.research_summary}</p>
              </div>
            )}
            {app.education_history && (
              <div className="rounded-md border border-outline-variant px-3 py-2">
                <p className="text-label text-on-surface-variant mb-1">{t("教育与科研经历")}</p>
                <p className="text-body-sm text-on-surface whitespace-pre-wrap">{app.education_history}</p>
              </div>
            )}
            {app.submitted_at && (
              <p className="text-label text-on-surface-variant">
                {t("飞书提交时间：{v}", { v: app.submitted_at.slice(0, 16).replace("T", " ") })}
              </p>
            )}
          </div>
        )}

        {/* 材料 */}
        <div className="flex flex-col gap-3">
          <p className="text-title-lg">{t("申请材料（{n}）", { n: app.materials?.length ?? 0 })}</p>
          {groupedMaterials.length === 0 ? (
            <p className="text-body-sm text-on-surface-variant">{t("暂无材料")}</p>
          ) : (
            groupedMaterials.map(([kind, items]) => (
              <div key={kind} className="flex flex-col gap-1.5">
                <p className="text-label text-on-surface-variant">
                  {t(MATERIAL_KIND_LABELS[kind] ?? kind)}{t("（{n}）", { n: items.length })}
                </p>
                {items.map((m) => (
                  <details key={m.id} className="border border-outline-variant rounded-lg px-3 py-2 group">
                    <summary className="text-body-sm text-on-surface cursor-pointer select-none flex items-center gap-2">
                      <Icon name="description" size={16} className="text-on-surface-variant" />
                      {m.filename}
                      {m.kind === "letter" && m.advisor_name && (
                        <span className="text-label text-on-surface-variant">{t("推荐人：{name}", { name: m.advisor_name })}</span>
                      )}
                    </summary>
                    <pre className="mt-2 text-label text-on-surface-variant whitespace-pre-wrap break-words max-h-72 overflow-y-auto">
                      {m.raw_text || t("（无文本内容）")}
                    </pre>
                  </details>
                ))}
              </div>
            ))
          )}
        </div>
      </Card>
    );
  }
}
