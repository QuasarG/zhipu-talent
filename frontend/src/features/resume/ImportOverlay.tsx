import { useRef, useState } from "react";
import type { DragEvent as ReactDragEvent } from "react";
import { api, parseSSE } from "@/lib/api";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import { IconButton } from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/Chip";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";

interface Props {
  onClose: () => void;
  /** 每份简历落库（候选人就绪）时回调：用于实时刷新队列，不等整个导入结束 */
  onCandidate?: () => void;
  /** 单次结构化响应流完成一个字段组时回调，立即填入详情预览 */
  onStructure?: (fileName: string, fields: Record<string, unknown>) => void;
}

interface FileState {
  name: string;
  status: "waiting" | "running" | "done" | "error";
  stage: string;
}

export default function ImportOverlay({ onClose, onCandidate, onStructure }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<FileState[]>([]);
  const [importing, setImporting] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const { t } = useI18n();

  const ACCEPTED_EXTS = [".pdf", ".jsonl", ".md", ".txt", ".png", ".jpg", ".jpeg", ".webp"];

  const startImport = (list: File[]) => {
    if (!list.length) return;
    const dt = new DataTransfer();
    list.forEach((f) => dt.items.add(f));
    void handleFiles(dt.files);
  };

  const handleDrop = (e: ReactDragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const dropped = Array.from(e.dataTransfer.files).filter((f) =>
      ACCEPTED_EXTS.some((ext) => f.name.toLowerCase().endsWith(ext))
    );
    startImport(dropped);
  };

  const handleFiles = async (fileList: FileList) => {
    const list = Array.from(fileList);
    if (!list.length) return;
    const initial: FileState[] = list.map((f) => ({ name: f.name, status: "waiting", stage: t("等待中") }));
    setFiles(initial);
    setImporting(true);
    let hasError = false;

    const formData = new FormData();
    list.forEach((f) => formData.append("files", f));

    try {
      const resp = await api.import(formData);
      if (!resp.ok) throw new Error(t("导入失败"));
      for await (const event of parseSSE(resp)) {
        const e = event as { type: string; file_id?: string; file_name?: string; status?: string; stage?: string; message?: string; section?: string; fields?: Record<string, unknown>; done?: number; total?: number; imported_files?: number; failed_files?: number };
        if (!e.file_id) {
          if (e.type === "done") break;
          continue;
        }
        if (e.type === "candidate") {
          // 候选人已落库：该文件卡片立即移除（核验后台进行，队列轮询更新），
          // 并实时刷新队列，不陪跑同批次其他文件
          setFiles((prev) => prev.filter((f) => f.name !== e.file_name));
          onCandidate?.();
          continue;
        }
        if (e.type === "error") hasError = true;
        setFiles((prev) =>
          prev.map((f) => {
            if (f.name !== e.file_name) return f;
            if (e.type === "structure") {
              // 完整字段组透传给详情窗口实时填充，卡片本身只更新阶段文案
              onStructure?.(f.name, e.fields || {});
              return { ...f, status: "running", stage: t("正在解析结构化字段…") };
            }
            if (e.type === "stage") {
              // stage 事件只更新进度文案，status 始终 running
              return { ...f, status: "running", stage: e.message || e.stage || "" };
            }
            if (e.type === "error") {
              return { ...f, status: "error", stage: e.message || t("失败于 {stage}", { stage: e.stage ?? "" }) };
            }
            return f;
          })
        );
      }
      // SSE 流结束（收到顶层 done）后，剩余文件标记完成并移除
      setFiles((prev) => prev.filter((f) => f.status !== "running"));
    } catch (error) {
      hasError = true;
      const message = error instanceof Error ? error.message : t("导入失败");
      setFiles((prev) => prev.map((f) => (
        f.status === "done" || f.status === "error"
          ? f
          : { ...f, status: "error", stage: message }
      )));
    } finally {
      setImporting(false);
      // 有失败卡片时保留让用户看到；全部成功则直接关闭
      if (!hasError) setTimeout(onClose, 1200);
    }
  };

  return (
    <div className="fixed bottom-6 left-[calc(72px+20px+16px)] w-[320px] z-[150]">
      <Card variant="elevated" className="p-4 max-h-[60vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-3">
          <span className="text-title">{t("导入简历")}</span>
          <IconButton icon="close" size={18} onClick={onClose} title={t("关闭")} />
        </div>

        {files.length === 0 && importing ? (
          <p className="py-4 text-center text-body-sm text-on-surface-variant">{t("候选人已全部进队列，正在收尾…")}</p>
        ) : files.length === 0 ? (
          <button
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragEnter={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={handleDrop}
            className={cn(
              "state-layer w-full py-6 rounded-md border border-dashed text-body-sm cursor-pointer flex flex-col items-center gap-2 transition-colors",
              dragActive
                ? "border-primary bg-primary-container/40 text-primary"
                : "border-outline text-on-surface-variant"
            )}
          >
            <Icon name="upload_file" size={24} />
            {dragActive ? t("松开以导入文件") : t("选择或拖入 PDF / 图片 / JSONL / MD / TXT 文件")}
          </button>
        ) : (
          <div className="flex flex-col gap-2">
            {files.map((f, i) => (
              <div key={i} className="p-2 rounded-sm bg-surface-low">
                <div className="flex items-center justify-between gap-2 mb-0.5">
                  <span className="text-body-sm font-medium truncate">{f.name}</span>
                  <StatusChip
                    className="shrink-0"
                    tone={
                      f.status === "done" ? "success" :
                      f.status === "error" ? "error" :
                      f.status === "running" ? "primary" : "neutral"
                    }
                  >
                    {f.status === "done" ? t("完成") : f.status === "error" ? t("失败") : f.status === "running" ? f.stage : t("等待")}
                  </StatusChip>
                </div>
                <p className="text-label text-on-surface-variant">{f.stage}</p>
              </div>
            ))}
          </div>
        )}

        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.jsonl,.md,.txt,.png,.jpg,.jpeg,.webp"
          multiple
          hidden
          onChange={(e) => e.target.files && handleFiles(e.target.files)}
        />
      </Card>
    </div>
  );
}
