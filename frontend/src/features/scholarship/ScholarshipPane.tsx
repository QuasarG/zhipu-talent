// 奖学金资料工作台：申请人信息 / 材料预览 / 评估与核验
import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { ChatCitation, ChatEvent, ChatMessage, ChatSegment, ScholarshipApplication, ScholarshipEvaluation, ScholarshipMaterial, ScorerTraceSegment } from "@/lib/types";
import Button, { IconButton } from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import { StatusChip } from "@/components/ui/Chip";
import { parseSSE } from "@/lib/api";
import AssistantMessage from "@/features/chat/AssistantMessage";
import { applyEvent, type LocalMessage as LocalChatMessage } from "@/pages/TalentChat";
import { RecordSection, MetaField, RecordIndex } from "@/features/resume/ResumeContent";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import Progress from "@/components/ui/Progress";
import Tabs from "@/components/ui/Tabs";
import { cn } from "@/lib/cn";
import {
  DEGREE_LABELS,
  KIND_ORDER,
  MATERIAL_KIND_LABELS,
  STATUS_LABELS,
  STATUS_TONES,
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

/** 评分总览统计带单元格：对齐结构化简历的 MetaField 语系（小标签在上，值在下），数字用等宽 */
function StatCell({ label, value, emphasis = false }: { label: string; value: ReactNode; emphasis?: boolean }) {
  const numeric = typeof value === "string";
  return (
    <div className="min-w-0 bg-surface-lowest px-4 py-3">
      <p className="text-label text-on-surface-variant">{label}</p>
      <div className={cn(
        "mt-1.5 flex min-h-7 items-center",
        numeric ? cn("font-mono tabular-nums leading-none text-on-surface", emphasis ? "text-display" : "text-headline") : "",
      )}>
        {value}
      </div>
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

const TOOL_LABELS: Record<string, string> = {
  list_files: "盘点材料",
  read_file: "读取材料",
  verify_paper: "论文查证",
  web_search: "全网检索",
  submit_scores: "提交评分",
};
const EVIDENCE_LABELS: Record<string, string> = {
  verified: "已验证",
  supported: "佐证可信",
  claimed: "仅自述",
};
const TIER_LABELS: Record<string, string> = {
  strong: "强推荐",
  recommend: "推荐",
  borderline: "边缘",
  not_recommend: "不推荐",
};
const TIER_TONES: Record<string, "success" | "primary" | "warning" | "error"> = {
  strong: "success",
  recommend: "primary",
  borderline: "warning",
  not_recommend: "error",
};
type AssessmentTab = "score" | "process";
const EMPTY_MATERIALS: ScholarshipMaterial[] = [];
/** 稳定空引用数组：每 tick 新建会让 AssistantMessage 的 plugins 重建，触发全量 markdown 重解析（闪烁） */
const EMPTY_CITATIONS: ChatCitation[] = [];
const NO_ON_DECIDE = () => {};

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

function isVideoFile(filename: string): boolean {
  return /\.(mp4|webm|mov|m4v)$/i.test(filename);
}

function materialIcon(filename: string): string {
  const name = filename.toLowerCase();
  if (name.endsWith(".pdf")) return "picture_as_pdf";
  if (/\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(name)) return "image";
  if (/\.(docx?|pages|txt|md)$/i.test(name)) return "article";
  if (/\.(mp4|webm|mov|m4v)$/i.test(name)) return "movie";
  if (/\.(mp3|wav|m4a|flac)$/i.test(name)) return "music_note";
  if (/\.(py|sh|ipynb|js|ts|c|cpp|java|go|rs)$/i.test(name)) return "code";
  if (/\.(parquet|csv|json|jsonl|yaml|yml|toml)$/i.test(name)) return "dataset";
  if (/\.(zip|rar|7z|tar|gz)$/i.test(name)) return "folder_zip";
  if (/\.(pptx?|key)$/i.test(name)) return "presentation";
  if (/\.(xlsx?|numbers)$/i.test(name)) return "table_chart";
  return "description";
}

function materialType(filename: string): string {
  const suffix = filename.split(".").pop()?.toUpperCase();
  return suffix && suffix.length <= 5 ? suffix : "FILE";
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
          {groupedMaterials.filter(([kind]) => kind !== "code").length === 0 ? (
            <div className="flex h-full min-h-36 flex-col items-center justify-center gap-2 px-4 text-center text-on-surface-variant">
              <Icon name="folder_open" size={26} />
              <p className="text-body-sm">{t("暂无材料")}</p>
            </div>
          ) : (
            <div className="p-2">
              {groupedMaterials.filter(([kind]) => kind !== "code").map(([kind, items]) => (
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
                            <span className="mt-0.5 flex items-center gap-1 text-label opacity-70">
                              {materialType(material.filename)}
                              {material.has_file && <Icon name="attach_file" size={11} />}
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
              <div className="flex shrink-0 items-center gap-3 border-b border-outline-variant px-4 py-2.5">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-secondary-container text-on-secondary-container">
                  <Icon name={materialIcon(selected.filename)} size={17} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-body-sm font-medium text-on-surface">{selected.filename}</p>
                  <p className="mt-0.5 text-label text-on-surface-variant">
                    {materialType(selected.filename)} · {t(MATERIAL_KIND_LABELS[selected.kind] ?? selected.kind)}
                    {selected.advisor_name ? ` · ${selected.advisor_name}` : ""}
                  </p>
                </div>
                {selected.has_file && (
                  <a
                    href={api.scholarship.materialDownloadUrl(selected.id)}
                    download
                    className="flex size-8 shrink-0 items-center justify-center rounded-full text-on-surface-variant transition-colors hover:bg-surface-low hover:text-on-surface"
                    title={t("下载原件")}
                  >
                    <Icon name="download" size={17} />
                  </a>
                )}
              </div>
              <div className="min-h-0 flex-1 overflow-hidden">
                {selected.has_file ? (
                  isVideoFile(selected.filename) ? (
                    <video
                      key={selected.id}
                      src={api.scholarship.materialPreviewUrl(selected.id)}
                      controls
                      playsInline
                      className="h-full w-full bg-surface-lowest object-contain"
                    />
                  ) : (
                    <iframe
                      key={selected.id}
                      src={api.scholarship.materialPreviewUrl(selected.id)}
                      title={selected.filename}
                      className="h-full w-full border-0 bg-surface-lowest"
                    />
                  )
                ) : (
                  <div className="flex h-full min-h-40 flex-col items-center justify-center gap-2 px-5 text-center text-on-surface-variant">
                    <Icon name="visibility_off" size={26} />
                    <p className="text-body-sm">{t("该材料未保存原件（历史数据仅有提取文本）")}</p>
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

/** 回放路径：后端存的旧 trace 段 → 问答 ChatSegment（与 live 流式同构，AssistantMessage 统一渲染） */
function traceToChatSegments(trace: ScorerTraceSegment[]): ChatSegment[] {
  const segs: ChatSegment[] = [];
  for (const seg of trace) {
    if (seg.type === "tool")
      segs.push({ type: "tool", call_id: seg.call_id, tool: seg.tool, label: seg.label || TOOL_LABELS[seg.tool] || seg.tool, status: seg.status === "error" ? "error" : "ok", summary: seg.summary, detail: seg.detail, args_summary: "" });
    else if (seg.type === "thinking") segs.push({ type: "thinking", text: seg.text });
    else if (seg.type === "text") segs.push({ type: "text", text: seg.text });
  }
  return segs;
}

export default function ScholarshipPane({
  app, loading, missingSelection, view, onRefresh, onDeleted, addDialog,
}: ScholarshipPaneProps) {
  const { t } = useI18n();
  const [error, setError] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [liveTrace, setLiveTrace] = useState<ChatSegment[] | null>(null);
  const latestEval = app?.evaluations?.[app.evaluations.length - 1];
  /** 评估过程页渲染源：live 流式时直接是 applyEvent 维护的消息；回放时由 trace 转换 */
  const processMessage: ChatMessage = useMemo(() => {
    if (liveTrace) {
      return {
        id: `scoring-${app?.id ?? ""}`,
        conversation_id: "",
        role: "assistant",
        content: { segments: liveTrace },
        citations: EMPTY_CITATIONS,
        status: "running",
        created_at: new Date().toISOString(),
      };
    }
    return {
      id: `trace-${latestEval?.id ?? "none"}`,
      conversation_id: "",
      role: "assistant",
      content: { segments: traceToChatSegments(latestEval?.trace ?? []) },
      citations: EMPTY_CITATIONS,
      status: "completed",
      created_at: latestEval?.created_at ?? new Date().toISOString(),
    };
  }, [liveTrace, latestEval]);
  // 过程容器自动滚底：仅当用户本就贴在底部时跟随；上翻阅读即放手（否则每 token 被拽回=无法滚动）
  const processRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const [assessmentTab, setAssessmentTab] = useState<AssessmentTab>("score");

  const latestCompleted = useMemo(
    () => [...(app?.evaluations ?? [])].reverse().find((e) => e.status === "completed"),
    [app],
  );
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

  useEffect(() => {
    // 流式期间贴底跟随（用户上翻超过阈值即停止拽底）
    const el = processRef.current;
    if (liveTrace && el && stickToBottomRef.current) {
      el.scrollTo(0, el.scrollHeight);
    }
  }, [liveTrace]);

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
      setAssessmentTab("process");
      stickToBottomRef.current = true;
      // 直接复用问答的流式消息模型：SSE 事件 → applyEvent → segments，
      let live: LocalChatMessage = {
        id: `scoring-${app!.id}`,
        conversation_id: "",
        role: "assistant",
        content: { segments: [] },
        citations: [],
        status: "running",
        created_at: new Date().toISOString(),
      };
      setLiveTrace(live.content.segments);
      // 微任务合并：SSE 事件可能成批到达（150ms 攒批后一次多条），
      // 每帧只 commit 一次，减少整列 diff 频率
      let commitQueued = false;
      const commit = () => {
        if (commitQueued) return;
        commitQueued = true;
        queueMicrotask(() => {
          commitQueued = false;
          setLiveTrace([...live.content.segments]);
        });
      };
      try {
        const response = await api.scholarship.evaluateStream(app!.id);
        for await (const event of parseSSE(response)) {
          const type = String(event.type ?? "");
          const payload = (event.payload ?? {}) as Record<string, unknown>;
          if (type === "done") {
            const final = payload as unknown as ScholarshipEvaluation;
            setLiveTrace(traceToChatSegments(final.trace ?? []));
            break;
          }
          if (type === "error") throw new Error(String(payload.message ?? t("评估失败")));
          live = applyEvent(live, {
            type,
            payload: payload as never,
          } as ChatEvent);
          commit();
        }
      } finally {
        setLiveTrace(null);
        onRefresh();
      }
    });


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
    const canEvaluate = !["imported", "material_incomplete", "ineligible"].includes(app.status) && latestEval?.status !== "running";
    const findings = latestCompleted?.reputation_findings ?? [];

    return (
      <Card variant="filled" className="min-h-0 flex-1 min-w-0 overflow-hidden flex flex-col">
        <div className="shrink-0 border-b border-outline-variant px-5 py-4">
          <div className="flex items-start gap-3">
            <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-primary-container text-title text-on-primary-container">
              {(app.name || t("未命名")).charAt(0)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <h1 className="truncate text-headline font-bold leading-tight text-on-surface">{app.name || t("未命名")}</h1>
                {app.name_en && <span className="truncate text-body-sm text-on-surface-variant">{app.name_en}</span>}
                <StatusBadge status={app.status} />
                {app.feishu_record_id && <span className="inline-flex items-center gap-1 text-label text-on-surface-variant"><Icon name="cloud_done" size={13} />{t("飞书同步")}</span>}
              </div>
              <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 xl:grid-cols-4">
                <MetaField label={t("学校")} value={app.school} />
                <MetaField label={t("实验室")} value={app.lab} />
                <MetaField label={t("研究方向")} value={app.direction} />
                <MetaField label={t("学位与年级")} value={[app.degree_type ? t(DEGREE_LABELS[app.degree_type] ?? app.degree_type) : "", app.grade].filter(Boolean).join(" · ")} />
                <MetaField label={t("预计毕业")} value={app.expected_graduation} />
                <MetaField label={t("推荐导师")} wide value={
                  <>
                    {app.advisors?.join(t("、")) || "—"}
                    {app.advisor_title && <span className="ml-2 text-label text-on-surface-variant">{app.advisor_title}</span>}
                  </>
                } />
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
              {confirmingDelete ? (
                <>
                  <span className="text-label text-error">{t("确认删除？")}</span>
                  <IconButton icon="check" size={16} className="h-8 w-8" title={t("确认")} onClick={() => runAction("delete", async () => { await api.scholarship.remove(app.id); onDeleted(); })} />
                  <IconButton icon="close" size={16} className="h-8 w-8" title={t("取消")} onClick={() => setConfirmingDelete(false)} />
                </>
              ) : <IconButton icon="delete" size={18} title={t("删除")} disabled={!!acting} onClick={() => setConfirmingDelete(true)} />}
            </div>
          </div>
          {acting && <div className="mt-2 inline-flex items-center gap-1.5 text-label text-on-surface-variant"><LoadingIndicator size={13} />{acting === "evaluate" ? t("评估中…") : t("删除中…")}</div>}
          {error && <p className="mt-2 text-body-sm text-error">{error}</p>}
        </div>

        {view === "assessment" && (
          <Tabs
            value={assessmentTab}
            onChange={setAssessmentTab}
            className="shrink-0 px-2"
            items={[
              { value: "score", label: t("评分结果") },
              { value: "process", label: t("评估过程") },
            ]}
          />
        )}

        {view === "overview" && (
          <div className="grid min-h-0 flex-1 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.62fr)]">
            <div className="min-h-0 overflow-y-auto px-5 py-4">
              {(app.status === "material_incomplete" || app.status === "ineligible") && (
                <section className="mb-4 rounded-md border border-warning/40 bg-warning-container/40 px-4 py-3">
                  <div className="flex items-center gap-2 text-body-sm font-medium text-warning"><Icon name="warning" size={17} />{t("筛选需要处理")}</div>
                  {(app.screening_detail?.missing ?? []).length > 0 && <p className="mt-1 text-body-sm text-on-surface">{t("缺少材料：")}{(app.screening_detail.missing ?? []).map((kind) => t(MATERIAL_KIND_LABELS[kind] ?? kind)).join(t("、"))}</p>}
                  {(app.screening_detail?.reasons ?? []).map((reason) => <p key={reason} className="mt-1 text-body-sm text-error">{reason}</p>)}
                </section>
              )}

              <RecordSection title={t("研究方向简述")} icon="edit_note" meta={t("申请人自述")} className="mb-4">
                <div className="px-4 py-3">
                  <p className="max-h-40 overflow-y-auto whitespace-pre-wrap text-body-sm leading-6 text-on-surface">
                    {app.research_summary || t("暂无研究方向简述")}
                  </p>
                </div>
              </RecordSection>

              <RecordSection title={t("关键资料")} icon="badge" className="mb-4">
                <div className="grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-3">
                  <MetaField label={t("学校")} value={app.school} />
                  <MetaField label={t("实验室")} value={app.lab} />
                  <MetaField label={t("研究方向")} value={app.direction} />
                  <MetaField label={t("学位与年级")} value={[app.degree_type ? t(DEGREE_LABELS[app.degree_type] ?? app.degree_type) : "", app.grade].filter(Boolean).join(" · ")} />
                  <MetaField label={t("预计毕业")} value={app.expected_graduation} />
                  <MetaField label={t("申请来源")} value={app.feishu_record_id ? t("飞书问卷") : t("手动添加")} />
                  <MetaField label={t("导师")} wide value={app.advisors?.join(t("、"))} />
                </div>
              </RecordSection>

              <RecordSection title={t("教育与科研经历")} icon="school" className="mb-4" meta={app.submitted_at ? t("提交于 {v}", { v: formatDate(app.submitted_at) }) : undefined}>
                <div className="px-4 py-3">
                  <p className="max-h-40 overflow-y-auto whitespace-pre-wrap text-body-sm leading-6 text-on-surface">
                    {app.education_history || t("暂无教育与科研经历")}
                  </p>
                </div>
              </RecordSection>

              <RecordSection title={t("联系方式")} icon="contact_mail">
                <div className="grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-3">
                  <MetaField label={t("邮箱")} value={app.email} />
                  <MetaField label={t("电话")} value={app.phone} />
                  <MetaField label={t("所在地区")} value={app.country} />
                  <MetaField label={t("材料数量")} value={t("{n} 份", { n: materials.length })} />
                </div>
              </RecordSection>
            </div>
            <div className="min-h-0 border-t border-outline-variant p-4 lg:border-l lg:border-t-0">
              <MaterialExplorer materials={materials} groupedMaterials={groupedMaterials} compact />
            </div>
          </div>
        )}

        {view === "materials" && (
          <div className="flex min-h-0 flex-1 p-4"><MaterialExplorer materials={materials} groupedMaterials={groupedMaterials} /></div>
        )}

        {view === "assessment" && assessmentTab === "score" && (
          // 一页式布局：外层不滚动，各卡在剩余高度内排布，长内容在卡片体内部滚动
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-5 py-4">
            <RecordSection
              title={t("评分总览")}
              icon="workspace_premium"
              className="mb-4 shrink-0"
              meta={latestCompleted ? `${latestCompleted.config_version} · ${formatDate(latestCompleted.created_at)}` : undefined}
              action={
                <Button variant={latestCompleted || latestEval?.status === "failed" ? "tonal" : "filled"} icon="refresh" disabled={!!acting || !canEvaluate} onClick={handleEvaluate}>
                  {latestCompleted || latestEval?.status === "failed" ? t("重新评估") : t("开始评估")}
                </Button>
              }
            >
                  {latestEval?.status === "running" ? (
                    <div className="flex items-center justify-center px-4 py-10"><LoadingIndicator size={22} label={t("评估中…")} /></div>
                  ) : (
                    <>
                      {latestEval?.status === "failed" && (
                        <p className="border-b border-outline-variant bg-error-container/40 px-4 py-3 text-body-sm text-error">
                          {t("评估失败：{msg}", { msg: latestEval.error_message || t("未知错误") })}
                        </p>
                      )}
                      {latestCompleted ? (
                        <>
                          <div className="grid grid-cols-2 gap-px bg-outline-variant sm:grid-cols-4">
                            <StatCell label={t("当前总分")} emphasis value={fmtScore(app.total_score)} />
                            <StatCell label={t("脱敏盲评分")} value={fmtScore(app.blind_score)} />
                            <StatCell label={t("推荐档位")} value={
                              latestCompleted.recommend_tier
                                ? <StatusChip tone={TIER_TONES[latestCompleted.recommend_tier] ?? "neutral"} variant="filled">{t(TIER_LABELS[latestCompleted.recommend_tier] ?? latestCompleted.recommend_tier)}</StatusChip>
                                : "—"
                            } />
                            <StatCell label={t("评估状态")} value={
                              <StatusChip tone={latestEval?.status === "failed" ? "error" : "success"}>{latestEval?.status === "failed" ? t("评估失败") : t("已完成")}</StatusChip>
                            } />
                          </div>
                          <p className="border-t border-outline-variant px-4 py-2 text-label text-on-surface-variant">{t("已按脱敏分与舆情调整汇总")}</p>
                        </>
                      ) : (
                        <div className="flex flex-col items-center gap-1 px-4 py-10 text-center">
                          <p className="text-body-sm text-on-surface-variant">{t("尚未生成评分结果")}</p>
                        </div>
                      )}
                    </>
                  )}
                </RecordSection>

                {latestCompleted && (
                  <RecordSection title={t("评分明细")} icon="checklist" count={latestCompleted.dimensions.length} className="mb-4 flex min-h-0 flex-1 flex-col" bodyClassName="min-h-0 flex-1 overflow-y-auto">
                    <div className="divide-y divide-outline-variant">
                      {latestCompleted.dimensions.map((dimension, index) => {
                        const max = dimension.key === "integrity_risk" ? 10 : 5;
                        return (
                          <article key={dimension.key} className="grid grid-cols-[28px_minmax(0,1fr)] gap-3 px-4 py-3.5">
                            <RecordIndex value={index + 1} />
                            <div className="min-w-0">
                              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                                <h4 className="text-title font-bold text-on-surface">{dimension.label}</h4>
                                {dimension.evidence_level && (
                                  <StatusChip tone={dimension.evidence_level === "verified" ? "success" : dimension.evidence_level === "supported" ? "info" : "neutral"}>
                                    {t(EVIDENCE_LABELS[dimension.evidence_level] ?? dimension.evidence_level)}
                                  </StatusChip>
                                )}
                                <span className="ml-auto shrink-0 font-mono text-body font-medium tabular-nums text-on-surface">
                                  {fmtScore(dimension.score)}<span className="text-on-surface-variant">/{max}</span>
                                </span>
                                <span className="shrink-0 text-label text-on-surface-variant">{t("满分 {n}", { n: dimension.max_points })}</span>
                              </div>
                              <Progress value={(dimension.score / max) * 100} className="mt-2.5" />
                              {dimension.reason && <p className="mt-2 text-body-sm leading-6 text-on-surface-variant">{dimension.reason}</p>}
                            </div>
                          </article>
                        );
                      })}
                    </div>
                  </RecordSection>
                )}

                {latestCompleted && (
                  <div className="mb-4 grid shrink-0 grid-cols-1 gap-4 lg:grid-cols-2">
                    <RecordSection title={t("亮点")} icon="auto_awesome" bodyClassName="max-h-60 overflow-y-auto">
                      <ul className="divide-y divide-outline-variant">
                        {latestCompleted.highlights.map((highlight) => (
                          <li key={highlight} className="flex items-start gap-2 px-4 py-2.5 text-body-sm text-on-surface"><Icon name="check_circle" size={16} className="mt-0.5 shrink-0 text-success" />{highlight}</li>
                        ))}
                        {!latestCompleted.highlights.length && <li className="px-4 py-3 text-body-sm text-on-surface-variant">—</li>}
                      </ul>
                    </RecordSection>
                    <RecordSection title={t("风险")} icon="warning" bodyClassName="max-h-60 overflow-y-auto">
                      <ul className="divide-y divide-outline-variant">
                        {latestCompleted.risks.map((risk) => (
                          <li key={risk} className="flex items-start gap-2 px-4 py-2.5 text-body-sm text-on-surface"><Icon name="warning" size={16} className="mt-0.5 shrink-0 text-warning" />{risk}</li>
                        ))}
                        {!latestCompleted.risks.length && <li className="px-4 py-3 text-body-sm text-on-surface-variant">—</li>}
                      </ul>
                    </RecordSection>
                  </div>
                )}

                {findings.length > 0 && (
                  <RecordSection title={t("舆情发现")} icon="public" count={findings.length} className="shrink-0" bodyClassName="max-h-48 overflow-y-auto">
                    <ul className="divide-y divide-outline-variant">
                      {findings.map((f, i) => (
                        <li key={i} className="flex flex-wrap items-center gap-2 px-4 py-2.5 text-body-sm">
                          <StatusChip tone={f.sentiment === "negative" ? "error" : "success"} variant="dot">{f.sentiment === "negative" ? t("负面") : t("正面")}</StatusChip>
                          <a href={f.url} target="_blank" rel="noreferrer" className="text-primary hover:underline">{f.title || f.url}</a>
                          {f.note && <span className="text-label text-on-surface-variant">{f.note}</span>}
                        </li>
                      ))}
                    </ul>
                    <p className="border-t border-outline-variant px-4 py-2 text-label text-on-surface-variant">{t("舆情发现（供人工参考，不计入自动分）")}</p>
                  </RecordSection>
                )}
          </div>
        )}

        {view === "assessment" && assessmentTab === "process" && (
          <div
            ref={processRef}
            onScroll={(e) => {
              const el = e.currentTarget;
              stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
            }}
            className="min-h-0 flex-1 overflow-y-auto"
          >
            <div className="mx-auto w-full max-w-4xl px-5 py-4">
              <div className="mb-5"><h2 className="text-title-lg">{t("评估过程")}</h2><p className="mt-1 text-body-sm text-on-surface-variant">{t("评审 agent 的工作记录：读了哪些材料、查证了什么、如何下结论")}</p></div>
              <AssistantMessage message={processMessage} busy={!!liveTrace} onDecide={NO_ON_DECIDE} />
            </div>
          </div>
        )}
      </Card>
    );
  }
}
