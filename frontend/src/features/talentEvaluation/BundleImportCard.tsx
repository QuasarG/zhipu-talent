// 材料导入卡：一人一 zip（或单份文件）。上传后自动定位包内简历、走原有
// 简历解析链路（/api/import-file：结构化解析+身份判定+入档），其余材料仅预览。
// 评估时 agent 自主读文件（奖学金模式），导入阶段不做任何 agent 转译。
import { useCallback, useEffect, useRef, useState } from "react";
import { api, authedFetch, parseSSE } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { TalentBundleSummary } from "@/lib/types";
import Button, { IconButton } from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import { StatusChip } from "@/components/ui/Chip";

const STATUS_TONES: Record<string, "success" | "info" | "error" | "neutral" | "warning"> = {
  imported: "success", importing: "info", failed: "error", unpacked: "neutral", noresume: "warning",
};

interface Props {
  onClose: () => void;
  /** 有包完成导入（人已入档）时通知外层刷新人才列表 */
  onChanged: () => void;
}

export default function BundleImportCard({ onClose, onChanged }: Props) {
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement>(null);
  const [bundles, setBundles] = useState<TalentBundleSummary[]>([]);
  const [logs, setLogs] = useState<Record<string, string[]>>({});
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

  const pushLog = useCallback((id: string, line: string) => {
    setLogs((current) => ({ ...current, [id]: [...(current[id] ?? []).slice(-6), line] }));
  }, []);

  const importBundle = useCallback(async (bundle: TalentBundleSummary) => {
    const setLocal = (patch: Partial<TalentBundleSummary>) =>
      setBundles((current) => current.map((b) => (b.id === bundle.id ? { ...b, ...patch } : b)));
    setLogs((current) => ({ ...current, [bundle.id]: [] }));
    try {
      if (!bundle.resume_file) {
        setLocal({ status: "failed", error_message: t("未在包内定位到简历文件（文件名需含 简历/resume/cv，或包内仅一个 pdf）") });
        return;
      }
      setLocal({ status: "importing" });
      pushLog(bundle.id, t("下载包内简历文件…"));
      const blob = await fetch(`/api/talent-bundles/${bundle.id}/file?path=${encodeURIComponent(bundle.resume_file)}`)
        .then((r) => { if (!r.ok) throw new Error(t("简历文件下载失败")); return r.blob(); });
      const file = new File([blob], bundle.resume_file.split("/").pop() || "resume.pdf", { type: "application/octet-stream" });

      pushLog(bundle.id, t("走原有简历解析链路：结构化解析 + 身份判定 + 入档…"));
      const form = new FormData();
      form.append("files", file);
      const response = await authedFetch("/api/import-file", { method: "POST", body: form });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      let candidateId = "";
      for await (const event of parseSSE(response)) {
        const e = event as { type: string; message?: string };
        if (e.type === "candidate") {
          const payload = (event.payload ?? {}) as Record<string, unknown>;
          candidateId = String(payload.id ?? "");
        }
        if (e.type === "stage" && e.message) pushLog(bundle.id, String(e.message));
        if (e.type === "done") break;
      }
      if (!candidateId) throw new Error(t("解析完成但未返回候选人"));
      await api.talentBundle.link(bundle.id, candidateId);
      pushLog(bundle.id, t("已入人才档案"));
      setLocal({ status: "imported", candidate_id: candidateId });
      onChanged();
    } catch (err) {
      const message = err instanceof Error ? err.message : t("操作失败");
      setLocal({ status: "failed", error_message: message });
      pushLog(bundle.id, message);
    } finally {
      void load();
    }
  }, [load, onChanged, pushLog, t]);

  const upload = useCallback(async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    setError("");
    try {
      const result = await api.talentBundle.upload(Array.from(files));
      await load();
      if (result.errors.length) setError(result.errors.map((e) => `${e.filename}: ${e.error}`).join("；"));
      // 上传成功即自动解析：定位简历 → 原有解析链路 → 入档
      for (const bundle of result.created) {
        await importBundle(bundle);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("操作失败"));
    } finally {
      setUploading(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }, [importBundle, load, t]);

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
          {t("zip 材料包（一人一包）或单份文件均可；自动解析包内简历入档，其余材料仅预览，评估时 agent 自主读取")}
        </p>
        {error && <p className="mb-2 text-body-sm text-error">{error}</p>}

        {!bundles.length ? (
          <p className="py-4 text-center text-body-sm text-on-surface-variant">
            {t("还没有材料；上传 zip（一人一包）或单份文件")}
          </p>
        ) : (
          <div className="flex flex-col gap-1">
            {bundles.map((bundle) => (
              <div key={bundle.id} className="rounded-md border border-outline-variant bg-surface-lowest px-3 py-2">
                <div className="flex items-center gap-2">
                  <Icon name="folder_zip" size={16} className="shrink-0 text-on-surface-variant" />
                  <span className="min-w-0 flex-1 truncate text-body-sm">{bundle.filename}</span>
                  <span className="shrink-0 text-label text-on-surface-variant">{bundle.file_count} 个文件</span>
                  <StatusChip tone={STATUS_TONES[bundle.status] ?? "neutral"}>
                    {t(bundle.status === "importing" ? "解析中…" : bundle.status === "imported" ? "已入档" : bundle.status === "failed" ? "解析失败" : "待解析")}
                  </StatusChip>
                  {bundle.status === "unpacked" && bundle.resume_file && (
                    <Button variant="outlined" className="h-7 px-2 text-xs shrink-0"
                      onClick={() => void importBundle(bundle)}>
                      {t("解析入档")}
                    </Button>
                  )}
                </div>
                {(logs[bundle.id]?.length || bundle.status === "failed") && (
                  <div className="mt-1.5 pl-6">
                    {bundle.status === "failed" && bundle.error_message && (
                      <p className="text-label text-error">{bundle.error_message}</p>
                    )}
                    <ul className="space-y-0.5">
                      {(logs[bundle.id] ?? []).map((line, i) => (
                        <li key={i} className="text-label text-on-surface-variant">· {line}</li>
                      ))}
                    </ul>
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
