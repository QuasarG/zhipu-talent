import { Fragment, useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import type { ScholarshipApplication } from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import Card from "@/components/ui/Card";
import Button, { IconButton } from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/Chip";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import { cn } from "@/lib/cn";
import {
  DEGREE_LABELS,
  MATERIAL_KIND_LABELS,
  STATUS_LABELS,
  STATUS_TONES,
  fmtAdjust,
  fmtScore,
} from "@/features/scholarship/scholarshipModel";

export function ScholarshipStatusChip({ status }: { status: string }) {
  return (
    <StatusChip tone={STATUS_TONES[status] ?? "neutral"}>
      {STATUS_LABELS[status] ?? status}
    </StatusChip>
  );
}

const inputClass =
  "h-9 px-3 rounded-sm border border-outline-variant bg-surface-lowest text-body-sm text-on-surface outline-none focus:outline-2 focus:outline-primary";

interface DialogProps {
  onClose: () => void;
  onDone: () => void;
}

/** 添加申请人：填表 → 传材料 → 自动筛选并展示结果 */
function AddApplicantDialog({ onClose, onDone }: DialogProps) {
  const [step, setStep] = useState<"form" | "upload" | "result">("form");
  const [form, setForm] = useState({
    name: "",
    degree_type: "master",
    expected_graduation: "",
    direction: "",
    school: "",
    advisors: "",
  });
  const [created, setCreated] = useState<ScholarshipApplication | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [screenResult, setScreenResult] = useState<{ status: string; missing: string[]; reasons: string[] } | null>(null);

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
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setBusy(false);
    }
  };

  // 传完材料立即筛选；也允许跳过上直接筛选
  const uploadAndScreen = async (withFiles: boolean) => {
    if (!created || busy) return;
    setBusy(true);
    setError("");
    try {
      if (withFiles && files.length) await api.scholarship.uploadMaterials(created.id, files);
      const result = await api.scholarship.screen(created.id);
      setScreenResult(result);
      setStep("result");
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const close = () => {
    onDone();
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-inverse-surface/30" onClick={close}>
      <Card variant="elevated" className="w-[440px] p-5 flex flex-col gap-3" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <p className="text-title-lg">
            {step === "form" ? "添加申请人" : step === "upload" ? "上传申请材料" : "筛选结果"}
          </p>
          <IconButton icon="close" onClick={close} title="关闭" />
        </div>

        {step === "form" && (
          <>
            <input type="text" value={form.name} placeholder="姓名（必填）" className={inputClass}
              onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))} />
            <select value={form.degree_type} className={cn(inputClass, "cursor-pointer")}
              onChange={(e) => setForm((p) => ({ ...p, degree_type: e.target.value }))}>
              <option value="master">硕士</option>
              <option value="phd">博士</option>
            </select>
            <input type="text" value={form.expected_graduation} placeholder="预计毕业时间（YYYY-MM）" className={inputClass}
              onChange={(e) => setForm((p) => ({ ...p, expected_graduation: e.target.value }))} />
            <input type="text" value={form.direction} placeholder="研究方向" className={inputClass}
              onChange={(e) => setForm((p) => ({ ...p, direction: e.target.value }))} />
            <input type="text" value={form.school} placeholder="学校" className={inputClass}
              onChange={(e) => setForm((p) => ({ ...p, school: e.target.value }))} />
            <input type="text" value={form.advisors} placeholder="推荐导师（逗号分隔）" className={inputClass}
              onChange={(e) => setForm((p) => ({ ...p, advisors: e.target.value }))} />
            <Button variant="filled" icon="arrow_forward" className="w-full" disabled={!form.name.trim() || busy} onClick={submitForm}>
              {busy ? "创建中…" : "下一步：上传材料"}
            </Button>
          </>
        )}

        {step === "upload" && (
          <>
            <p className="text-body-sm text-on-surface-variant">
              为「{created?.name}」上传材料：支持 zip 打包或多选散装文件，推荐信最多 2 封
            </p>
            <input
              type="file"
              multiple
              className="text-body-sm text-on-surface-variant"
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            />
            {files.length > 0 && (
              <p className="text-label text-on-surface-variant">已选 {files.length} 个文件</p>
            )}
            <Button variant="filled" icon="upload" className="w-full" disabled={busy} onClick={() => uploadAndScreen(true)}>
              {busy ? "处理中…" : files.length ? "上传并筛选" : "直接筛选"}
            </Button>
            <Button variant="text" className="w-full" disabled={busy} onClick={() => uploadAndScreen(false)}>
              跳过上传，直接筛选
            </Button>
          </>
        )}

        {step === "result" && screenResult && (
          <>
            <div className="flex items-center gap-2">
              <span className="text-body-sm text-on-surface-variant">{created?.name}</span>
              <ScholarshipStatusChip status={screenResult.status} />
            </div>
            {screenResult.missing.length > 0 && (
              <p className="text-body-sm text-warning">
                缺少材料：{screenResult.missing.map((k) => MATERIAL_KIND_LABELS[k] ?? k).join("、")}
              </p>
            )}
            {screenResult.reasons.length > 0 && (
              <ul className="text-body-sm text-error list-disc pl-5">
                {screenResult.reasons.map((r) => <li key={r}>{r}</li>)}
              </ul>
            )}
            <Button variant="tonal" className="w-full" onClick={close}>完成</Button>
          </>
        )}

        {error && <p className="text-label text-error">{error}</p>}
      </Card>
    </div>
  );
}

export default function Scholarship() {
  const navigate = useNavigate();
  const [apps, setApps] = useState<ScholarshipApplication[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  // 行内操作防重：id → 正在执行的动作名
  const [busy, setBusy] = useState<Record<string, string>>({});
  const [confirmingId, setConfirmingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setApps(await api.scholarship.list());
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const runAction = async (id: string, action: string, fn: () => Promise<void>) => {
    if (busy[id]) return;
    setBusy((p) => ({ ...p, [id]: action }));
    setError("");
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy((p) => {
        const next = { ...p };
        delete next[id];
        return next;
      });
    }
  };

  // 评估接口同步阻塞返回，返回后再轮询兜底确认最新评估已结束
  const waitEvaluationDone = async (id: string) => {
    for (let i = 0; i < 30; i++) {
      const d = await api.scholarship.get(id);
      const latest = d.evaluations?.[d.evaluations.length - 1];
      if (!latest || latest.status !== "running") return;
      await new Promise((r) => setTimeout(r, 2000));
    }
  };

  const handleScreen = (id: string) =>
    runAction(id, "screen", async () => {
      await api.scholarship.screen(id);
      await load();
    });

  const handleEvaluate = (id: string) =>
    runAction(id, "evaluate", async () => {
      await api.scholarship.evaluate(id);
      await waitEvaluationDone(id);
      await load();
    });

  const handleScan = (id: string) =>
    runAction(id, "scan", async () => {
      await api.scholarship.reputationScan(id);
      await load();
    });

  const handleDelete = (id: string) =>
    runAction(id, "delete", async () => {
      await api.scholarship.remove(id);
      setConfirmingId(null);
      await load();
    });

  return (
    <div className="w-full max-w-full h-[calc(100vh-48px)] min-h-0 min-w-0 overflow-hidden flex flex-col">
      <PageToolbar
        title="奖学金初筛"
        subtitle="Z.AI Scholarship 2026 · 材料筛查 → 盲评 → 舆情核验"
        right={
          <>
            <IconButton icon="refresh" variant="outlined" onClick={load} title="刷新" />
            <Button icon="person_add" onClick={() => setShowAdd(true)}>添加申请人</Button>
          </>
        }
      />

      {error && <p className="text-body-sm text-error px-2 mb-2">{error}</p>}

      <Card variant="filled" className="flex-1 min-h-0 overflow-y-auto p-4">
        {loading ? (
          <div className="flex justify-center py-10"><LoadingIndicator size={28} label="加载中…" /></div>
        ) : apps.length === 0 ? (
          <p className="text-body-sm text-on-surface-variant py-10 text-center">还没有申请人，点右上角「添加申请人」开始</p>
        ) : (
          <table className="w-full text-body-sm">
            <thead>
              <tr className="text-label text-on-surface-variant text-left">
                <th className="pb-2 font-medium">姓名</th>
                <th className="pb-2 font-medium">学校</th>
                <th className="pb-2 font-medium">方向</th>
                <th className="pb-2 font-medium">毕业时间</th>
                <th className="pb-2 font-medium">状态</th>
                <th className="pb-2 font-medium text-right">脱敏分</th>
                <th className="pb-2 font-medium text-right">舆情调整</th>
                <th className="pb-2 font-medium text-right">总分</th>
                <th className="pb-2 font-medium text-right">待核验</th>
                <th className="pb-2 font-medium text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {apps.map((a) => {
                const acting = busy[a.id];
                const { missing = [], reasons = [] } = a.screening_detail ?? {};
                const showDetail = (a.status === "material_incomplete" || a.status === "ineligible") && (missing.length > 0 || reasons.length > 0);
                return (
                  <Fragment key={a.id}>
                    <tr
                      onClick={() => navigate(`/scholarship/${a.id}`)}
                      className="cursor-pointer border-t border-outline-variant hover:bg-surface-low"
                    >
                      <td className="py-2 text-on-surface">
                        {a.name || "未命名"}
                        <span className="ml-1.5 text-label text-on-surface-variant">{DEGREE_LABELS[a.degree_type] ?? a.degree_type}</span>
                      </td>
                      <td className="py-2 text-on-surface-variant">{a.school || "—"}</td>
                      <td className="py-2 text-on-surface-variant max-w-40 truncate">{a.direction || "—"}</td>
                      <td className="py-2 text-on-surface-variant">{a.expected_graduation || "—"}</td>
                      <td className="py-2"><ScholarshipStatusChip status={a.status} /></td>
                      <td className="py-2 text-right text-on-surface-variant">{fmtScore(a.blind_score)}</td>
                      <td className={cn("py-2 text-right", a.reputation_adjustment < 0 ? "text-error" : "text-on-surface-variant")}>
                        {fmtAdjust(a.reputation_adjustment)}
                      </td>
                      <td className="py-2 text-right text-on-surface font-medium">{fmtScore(a.total_score)}</td>
                      <td className={cn("py-2 text-right", a.pending_reputation > 0 ? "text-warning" : "text-on-surface-variant")}>
                        {a.pending_reputation || "—"}
                      </td>
                      <td className="py-2" onClick={(e) => e.stopPropagation()}>
                        {acting ? (
                          <span className="inline-flex items-center justify-end gap-1.5 text-label text-on-surface-variant w-full">
                            <LoadingIndicator size={14} />
                            {acting === "evaluate" ? "评估中…" : acting === "screen" ? "筛选中…" : acting === "scan" ? "扫描中…" : "删除中…"}
                          </span>
                        ) : confirmingId === a.id ? (
                          <span className="inline-flex items-center justify-end gap-1 w-full">
                            <span className="text-label text-error">确认删除？</span>
                            <IconButton icon="check" size={16} className="w-8 h-8" title="确认" onClick={() => handleDelete(a.id)} />
                            <IconButton icon="close" size={16} className="w-8 h-8" title="取消" onClick={() => setConfirmingId(null)} />
                          </span>
                        ) : (
                          <span className="inline-flex items-center justify-end w-full">
                            <IconButton icon="fact_check" size={18} title="筛选" onClick={() => handleScreen(a.id)} />
                            <IconButton icon="grade" size={18} title="评估" onClick={() => handleEvaluate(a.id)} />
                            <IconButton icon="travel_explore" size={18} title="舆情扫描" onClick={() => handleScan(a.id)} />
                            <IconButton icon="delete" size={18} title="删除" onClick={() => setConfirmingId(a.id)} />
                          </span>
                        )}
                      </td>
                    </tr>
                    {showDetail && (
                      <tr className="text-label">
                        <td colSpan={10} className="pb-2 pt-0.5">
                          {missing.length > 0 && (
                            <span className="text-warning mr-3">缺少：{missing.map((k) => MATERIAL_KIND_LABELS[k] ?? k).join("、")}</span>
                          )}
                          {reasons.map((r) => (
                            <span key={r} className="text-error mr-3">{r}</span>
                          ))}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>

      {showAdd && <AddApplicantDialog onClose={() => setShowAdd(false)} onDone={load} />}
    </div>
  );
}
