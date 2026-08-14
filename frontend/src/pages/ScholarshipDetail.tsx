import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { ScholarshipApplication, ScholarshipMaterial } from "@/lib/types";
import Card from "@/components/ui/Card";
import Button, { IconButton } from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/Chip";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import Progress from "@/components/ui/Progress";
import Icon from "@/components/ui/Icon";
import { cn } from "@/lib/cn";
import { ScholarshipStatusChip } from "./Scholarship";
import {
  DEGREE_LABELS,
  KIND_ORDER,
  MATERIAL_KIND_LABELS,
  REVIEW_LABELS,
  SUBJECT_ROLE_LABELS,
  fmtAdjust,
  fmtScore,
} from "@/features/scholarship/scholarshipModel";

const inputClass =
  "h-9 px-3 rounded-sm border border-outline-variant bg-surface-lowest text-body-sm text-on-surface outline-none focus:outline-2 focus:outline-primary";

export default function ScholarshipDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [app, setApp] = useState<ScholarshipApplication | null>(null);
  const [error, setError] = useState("");
  const [notFound, setNotFound] = useState(false);
  const [brandBonus, setBrandBonus] = useState("0");
  const [brandNote, setBrandNote] = useState("");
  const [savingBrand, setSavingBrand] = useState(false);
  const [scanning, setScanning] = useState(false);
  // 舆情核验按钮防重：itemId → 进行中
  const [reviewing, setReviewing] = useState<Record<number, boolean>>({});

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const d = await api.scholarship.get(id);
      setApp(d);
      setBrandBonus(String(d.brand_bonus ?? 0));
      setBrandNote(d.brand_note ?? "");
    } catch (err) {
      setNotFound(true);
      setError(err instanceof Error ? err.message : t("加载失败"));
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // 最新一条 completed 评估用于展示维度明细
  const latestCompleted = useMemo(
    () => [...(app?.evaluations ?? [])].reverse().find((e) => e.status === "completed"),
    [app],
  );
  const latestEval = app?.evaluations?.[app.evaluations.length - 1];

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
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("保存失败"));
    } finally {
      setSavingBrand(false);
    }
  };

  const runScan = async () => {
    if (!app || scanning) return;
    setScanning(true);
    setError("");
    try {
      await api.scholarship.reputationScan(app.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("舆情扫描失败"));
    } finally {
      setScanning(false);
    }
  };

  const review = async (itemId: number, action: "confirmed" | "dismissed") => {
    if (reviewing[itemId]) return;
    setReviewing((p) => ({ ...p, [itemId]: true }));
    setError("");
    try {
      await api.scholarship.reviewReputation(itemId, action);
      await load();
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

  const { t } = useI18n();

  if (notFound) {
    return (
      <div className="flex flex-col items-center gap-3 py-20">
        <p className="text-body-sm text-error">{error || t("申请人不存在")}</p>
        <Button variant="tonal" icon="arrow_back" onClick={() => navigate("/scholarship")}>{t("返回列表")}</Button>
      </div>
    );
  }

  if (!app) {
    return <div className="flex justify-center py-20"><LoadingIndicator size={28} label={t("加载中…")} /></div>;
  }

  return (
    <div className="w-full max-w-full min-h-0 flex flex-col gap-4 pb-6">
      {/* 头部：返回 + 基本信息 + 状态 */}
      <div className="flex items-start gap-3 px-2 pt-3">
        <IconButton icon="arrow_back" variant="outlined" onClick={() => navigate("/scholarship")} title={t("返回列表")} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-headline leading-tight">{app.name || t("未命名")}</h1>
            <ScholarshipStatusChip status={app.status} />
          </div>
          <p className="text-body-sm text-on-surface-variant mt-1">
            {[app.school, t(DEGREE_LABELS[app.degree_type] ?? app.degree_type), app.direction, app.expected_graduation]
              .filter(Boolean).join(" · ") || "—"}
            {app.advisors.length > 0 && t(" · 推荐导师：{advisors}", { advisors: app.advisors.join(t("、")) })}
          </p>
        </div>
      </div>

      {error && <p className="text-body-sm text-error px-2">{error}</p>}

      {/* 三个分数卡 */}
      <div className="grid grid-cols-3 gap-4">
        <Card variant="filled" className="p-4">
          <p className="text-label text-on-surface-variant">{t("脱敏分")}</p>
          <p className="text-headline mt-1">{fmtScore(app.blind_score)}</p>
        </Card>
        <Card variant="filled" className="p-4">
          <p className="text-label text-on-surface-variant">{t("舆情调整")}</p>
          <p className={cn("text-headline mt-1", app.reputation_adjustment < 0 && "text-error")}>
            {fmtAdjust(app.reputation_adjustment)}
          </p>
        </Card>
        <Card variant="filled" className="p-4">
          <p className="text-label text-on-surface-variant">{t("总分")}</p>
          <p className="text-headline mt-1 text-primary">{fmtScore(app.total_score)}</p>
        </Card>
      </div>

      {/* 品牌加分 */}
      <Card variant="filled" className="p-4 flex flex-col gap-3">
        <p className="text-title-lg">{t("品牌加分")}</p>
        <div className="flex items-center gap-2 flex-wrap">
          <input
            type="number" step="0.5" min="-10" max="10"
            value={brandBonus}
            onChange={(e) => setBrandBonus(e.target.value)}
            className={cn(inputClass, "w-28")}
            placeholder={t("加分")}
          />
          <input
            type="text"
            value={brandNote}
            onChange={(e) => setBrandNote(e.target.value)}
            className={cn(inputClass, "flex-1 min-w-48")}
            placeholder={t("备注（如：目标院校品牌）")}
          />
          <Button variant="tonal" icon="save" disabled={savingBrand} onClick={saveBrand}>
            {savingBrand ? t("保存中…") : t("保存")}
          </Button>
        </div>
        {app.brand_note && (
          <p className="text-label text-on-surface-variant">{t("当前：{v} 分 · {note}", { v: fmtAdjust(app.brand_bonus), note: app.brand_note })}</p>
        )}
      </Card>

      {/* 维度评分明细 */}
      <Card variant="filled" className="p-4 flex flex-col gap-3">
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
          <p className="text-body-sm text-on-surface-variant">{t("暂无评估结果，回列表点「评估」")}</p>
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
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-label text-on-surface-variant mb-1.5">{t("亮点")}</p>
                <ul className="flex flex-col gap-1">
                  {latestCompleted.highlights.map((h) => (
                    <li key={h} className="flex items-start gap-1.5 text-body-sm text-on-surface">
                      <Icon name="check_circle" size={16} className="text-success shrink-0 mt-0.5" />
                      {h}
                    </li>
                  ))}
                  {latestCompleted.highlights.length === 0 && (
                    <li className="text-body-sm text-on-surface-variant">—</li>
                  )}
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
                  {latestCompleted.risks.length === 0 && (
                    <li className="text-body-sm text-on-surface-variant">—</li>
                  )}
                </ul>
              </div>
            </div>
          </>
        )}
      </Card>

      {/* 舆情核验 */}
      <Card variant="filled" className="p-4 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <p className="text-title-lg">{t("舆情核验")}</p>
          <Button variant="outlined" icon="travel_explore" disabled={scanning} onClick={runScan}>
            {scanning ? t("扫描中…") : t("发起舆情扫描")}
          </Button>
        </div>
        {(app.reputation_items ?? []).length === 0 ? (
          <p className="text-body-sm text-on-surface-variant">{t("暂无舆情条目，点右上发起扫描")}</p>
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
                <a
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-body-sm text-primary hover:underline"
                >
                  {item.title || item.url}
                </a>
                {item.snippet && <p className="text-label text-on-surface-variant">{item.snippet}</p>}
                {item.concern && <p className="text-body-sm text-error">{t("风险点：{concern}", { concern: item.concern })}</p>}
                {item.review_status === "pending" && (
                  <div className="flex items-center gap-2 mt-1">
                    <Button
                      variant="tonal" icon="check" className="h-8 px-4"
                      disabled={reviewing[item.id]}
                      onClick={() => review(item.id, "confirmed")}
                    >
                      {t("确认")}
                    </Button>
                    <Button
                      variant="outlined" icon="close" className="h-8 px-4"
                      disabled={reviewing[item.id]}
                      onClick={() => review(item.id, "dismissed")}
                    >
                      {t("驳回")}
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* 材料 */}
      <Card variant="filled" className="p-4 flex flex-col gap-3">
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
      </Card>
    </div>
  );
}
