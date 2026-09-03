// 材料包导入卡：一人一 zip 批量上传，双 agent（评估+督导）解析直接入档。
// 形态对齐 ImportOverlay：嵌在人才评估左栏的卡片，非独立页面。
import { useCallback, useEffect, useRef, useState } from "react";
import { api, parseSSE } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { ChatEvent, TalentBundle, TalentBundleSummary } from "@/lib/types";
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

interface Props {
  onClose: () => void;
  /** 有包完成解析（人已入档）时通知外层刷新人才列表 */
  onChanged: () => void;
}

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

export default function BundleImportCard({ onClose, onChanged }: Props) {
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement>(null);
  const streamRef = useRef<AbortController | null>(null);
  const [bundles, setBundles] = useState<TalentBundleSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TalentBundle | null>(null);
  const [live, setLive] = useState<LocalMessage | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

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
      if (inputRef.current) inputRef.current.value = "";
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
          setDetail(payload as unknown as TalentBundle);
          setLive(null);
          onChanged();
          void load();
          break;
        }
        if (type === "error") throw new Error(String(payload.message ?? t("操作失败")));
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
  }, [load, onChanged, t]);

  const shown = live ?? (detail ? traceToMessage(detail) : null);

  return (
    <div className="shrink-0">
      <Card variant="outlined" className="p-3 max-h-[60vh] overflow-y-auto border-primary/40">
        <div className="flex items-center justify-between mb-3">
          <span className="text-title">{t("导入材料")}</span>
          <div className="flex items-center gap-1.5">
            <input ref={inputRef} type="file" accept=".zip,.pdf,.docx,.png,.jpg,.jpeg,.webp,.txt,.md" multiple hidden
              onChange={(e) => void upload(e.target.files)} />
            <Button variant="tonal" icon="upload" className="h-8 px-3 text-xs" disabled={uploading}
              onClick={() => inputRef.current?.click()}>
              {uploading ? t("处理中…") : t("上传材料包")}
            </Button>
            <IconButton icon="close" size={18} onClick={onClose} title={t("关闭")} />
          </div>
        </div>
        <p className="mb-2 text-label text-on-surface-variant">
          {t("zip 材料包（一人一包）或单份文件均可；双 agent 解析后直接入人才档案")}
        </p>
        {error && <p className="mb-2 text-body-sm text-error">{error}</p>}

        {!bundles.length ? (
          <p className="py-4 text-center text-body-sm text-on-surface-variant">
            {t("还没有材料；上传 zip（一人一包）或单份文件")}
          </p>
        ) : (
          <div className="flex flex-col gap-1">
            {bundles.map((bundle) => (
              <div key={bundle.id} className="rounded-md border border-outline-variant bg-surface-lowest">
                <button
                  type="button"
                  onClick={() => void openBundle(bundle.id)}
                  className="state-layer flex w-full items-center gap-2 px-3 py-2 text-left cursor-pointer"
                >
                  <Icon name="folder_zip" size={16} className="shrink-0 text-on-surface-variant" />
                  <span className="min-w-0 flex-1 truncate text-body-sm">{bundle.filename}</span>
                  <span className="shrink-0 text-label text-on-surface-variant">{bundle.file_count} 个文件</span>
                  <StatusChip tone={STATUS_TONES[bundle.status] ?? "neutral"}>
                    {bundle.status === "profiling" && live && selectedId === bundle.id ? t("解析中…") : t(STATUS_LABELS[bundle.status] ?? bundle.status)}
                  </StatusChip>
                  {bundle.status === "unpacked" || bundle.status === "failed" ? (
                    <Button variant="outlined" className="h-7 px-2 text-xs shrink-0"
                      onClick={(e) => { e.stopPropagation(); void evaluate(bundle.id); }}>
                      {bundle.status === "failed" ? t("重试解析") : t("开始解析")}
                    </Button>
                  ) : bundle.status === "profiled" ? (
                    <Icon name="check_circle" size={16} className="shrink-0 text-success" />
                  ) : null}
                </button>
                {selectedId === bundle.id && (live || (detail && detail.id === bundle.id)) && (
                  <div className="max-h-72 overflow-y-auto border-t border-outline-variant px-3 py-2">
                    {shown && shown.content.segments.length ? (
                      <AssistantMessage message={shown} busy={!!live} onDecide={() => {}} />
                    ) : (
                      <p className="py-2 text-label text-on-surface-variant">
                        {t("尚未解析；点上方「开始解析」启动双 agent")}
                      </p>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
