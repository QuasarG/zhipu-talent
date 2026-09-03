// 人才材料包：一人一 zip 批量上传，双 agent（评估+督导）解析进档
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, parseSSE } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { ChatEvent, TalentBundle, TalentBundleSummary } from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import Button, { IconButton } from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import { StatusChip } from "@/components/ui/Chip";
import AssistantMessage from "@/features/chat/AssistantMessage";
import { applyEvent, type LocalMessage } from "@/pages/TalentChat";

const STATUS_TONES: Record<string, "success" | "info" | "error" | "neutral"> = {
  profiled: "success", profiling: "info", failed: "error", unpacked: "neutral",
};
const STATUS_LABELS: Record<string, string> = {
  profiled: "已入档", profiling: "解析中", failed: "失败", unpacked: "待解析",
};

function newLiveMessage(): LocalMessage {
  return {
    id: "bundle-live",
    conversation_id: "",
    role: "assistant",
    content: { segments: [] },
    citations: [],
    status: "running",
    created_at: new Date().toISOString(),
  };
}

export default function TalentBundles() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [bundles, setBundles] = useState<TalentBundleSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TalentBundle | null>(null);
  const [live, setLive] = useState<LocalMessage | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const streamRef = useRef<AbortController | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setBundles(await api.talentBundle.list());
    } catch (err) {
      setError(err instanceof Error ? err.message : t("加载失败"));
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => () => streamRef.current?.abort(), []);

  const openBundle = useCallback(async (id: string) => {
    setSelectedId(id);
    setLive(null);
    setError("");
    try {
      setDetail(await api.talentBundle.get(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("加载失败"));
    }
  }, [t]);

  const upload = useCallback(async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    setError("");
    try {
      const result = await api.talentBundle.upload(Array.from(files));
      await load();
      if (result.created.length) await openBundle(result.created[0].id);
      if (result.errors.length) setError(result.errors.map((e) => `${e.filename}: ${e.error}`).join("；"));
    } catch (err) {
      setError(err instanceof Error ? err.message : t("操作失败"));
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }, [load, openBundle, t]);

  const evaluate = useCallback(async (id: string) => {
    setError("");
    setLive(newLiveMessage());
    const controller = new AbortController();
    streamRef.current = controller;
    try {
      const response = await api.talentBundle.evaluateStream(id);
      for await (const event of parseSSE(response, controller.signal)) {
        const type = String(event.type ?? "");
        const payload = (event.payload ?? {}) as Record<string, unknown>;
        if (type === "done") {
          const snapshot = payload as unknown as TalentBundle;
          setDetail(snapshot);
          setLive(null);
          void load();
          break;
        }
        if (type === "error") {
          throw new Error(String(payload.message ?? t("操作失败")));
        }
        setLive((current) => (current ? applyEvent(current, { type, payload } as ChatEvent) : current));
      }
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setError(err instanceof Error ? err.message : t("操作失败"));
      }
      setLive(null);
    } finally {
      streamRef.current = null;
    }
  }, [load, t]);

  const busy = detail?.status === "profiling" || !!live;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageToolbar
        title={t("人才材料包")}
        subtitle={t("一人一 zip 批量上传 · 双 agent（评估+督导）解析直接入档")}
        right={
          <>
            <IconButton icon="refresh" size={18} title={t("刷新")} onClick={() => void load()} />
            <input
              ref={fileRef}
              type="file"
              accept=".zip"
              multiple
              hidden
              onChange={(e) => void upload(e.target.files)}
            />
            <Button variant="filled" icon="upload" disabled={uploading} onClick={() => fileRef.current?.click()}>
              {uploading ? t("处理中…") : t("上传材料包")}
            </Button>
          </>
        }
      />
      {error && <p className="px-5 pb-2 text-body-sm text-error">{error}</p>}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 p-4 pt-0 lg:grid-cols-[minmax(300px,0.4fr)_minmax(0,1fr)]">
        <Card variant="filled" className="min-h-0 overflow-y-auto p-2">
          {!bundles.length ? (
            <div className="flex h-full min-h-40 flex-col items-center justify-center gap-2 text-on-surface-variant">
              <Icon name="folder_zip" size={28} />
              <p className="text-body-sm">{t("还没有材料包；上传 zip 后自动按人拆包")}</p>
            </div>
          ) : (
            bundles.map((bundle) => (
              <button
                key={bundle.id}
                type="button"
                onClick={() => void openBundle(bundle.id)}
                className={`state-layer mb-1 flex w-full flex-col gap-1 rounded-md px-3 py-2.5 text-left cursor-pointer ${
                  selectedId === bundle.id ? "bg-primary-container text-on-primary-container" : "hover:bg-surface-low"
                }`}
              >
                <span className="flex items-center gap-2">
                  <Icon name="folder_zip" size={16} className="shrink-0" />
                  <span className="min-w-0 flex-1 truncate text-body-sm font-medium">{bundle.filename}</span>
                  <StatusChip tone={STATUS_TONES[bundle.status] ?? "neutral"}>{t(STATUS_LABELS[bundle.status] ?? bundle.status)}</StatusChip>
                </span>
                <span className="flex items-center gap-2 pl-6 text-label text-on-surface-variant">
                  {bundle.file_count} 个文件 · {(bundle.total_bytes / 1024 / 1024).toFixed(1)} MB · {bundle.created_at?.slice(0, 16).replace("T", " ")}
                </span>
              </button>
            ))
          )}
        </Card>

        <Card variant="filled" className="min-h-0 overflow-hidden flex flex-col">
          {!detail ? (
            <div className="flex flex-1 items-center justify-center text-on-surface-variant">
              <p className="text-body-sm">{t("从左侧选择材料包查看解析过程")}</p>
            </div>
          ) : (
            <>
              <div className="shrink-0 border-b border-outline-variant px-5 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="text-title-lg font-bold">{detail.filename}</h1>
                  <StatusChip tone={STATUS_TONES[detail.status] ?? "neutral"}>
                    {detail.status === "profiling" && live ? t("解析中…") : t(STATUS_LABELS[detail.status] ?? detail.status)}
                  </StatusChip>
                  <span className="text-label text-on-surface-variant">{detail.file_count} 个文件</span>
                  <span className="flex-1" />
                  {(detail.status === "unpacked" || detail.status === "failed") && (
                    <Button variant="filled" icon="play_arrow" disabled={busy} onClick={() => void evaluate(detail.id)}>
                      {detail.status === "failed" ? t("重试解析") : t("开始解析")}
                    </Button>
                  )}
                  {detail.status === "profiled" && detail.person_id && (
                    <Button variant="tonal" icon="person" onClick={() => navigate(`/talent-pool/${detail.person_id}`)}>
                      {t("查看档案")}
                    </Button>
                  )}
                </div>
                {detail.status === "failed" && detail.error_message && (
                  <p className="mt-2 text-body-sm text-error">{detail.error_message}</p>
                )}
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
                <div className="mx-auto w-full max-w-3xl">
                  {(live ? live : traceToMessage(detail)).content.segments.length ? (
                    <AssistantMessage
                      message={live ?? traceToMessage(detail)}
                      busy={!!live}
                      onDecide={() => {}}
                    />
                  ) : (
                    <div className="flex flex-col items-center gap-2 py-10 text-on-surface-variant">
                      <Icon name="smart_toy" size={28} />
                      <p className="text-body-sm">{t("尚未解析；点上方「开始解析」启动双 agent")}</p>
                    </div>
                  )}
                </div>
              </div>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}

/** 服务端持久化 trace（含 observer 泳道）→ AssistantMessage 消息模型 */
function traceToMessage(bundle: TalentBundle): LocalMessage {
  return {
    id: `bundle-trace-${bundle.id}`,
    conversation_id: "",
    role: "assistant",
    content: { segments: bundle.trace ?? [] },
    citations: [],
    status: "completed",
    created_at: bundle.created_at ?? new Date().toISOString(),
  };
}
