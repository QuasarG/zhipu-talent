import { useRef, useState } from "react";
import { api, parseSSE } from "@/lib/api";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import { IconButton } from "@/components/ui/Button";
import { StatusChip } from "@/components/ui/Chip";

interface Props {
  onClose: () => void;
}

interface FileState {
  name: string;
  status: "waiting" | "running" | "done" | "error";
  stage: string;
}

export default function ImportOverlay({ onClose }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<FileState[]>([]);
  const [, setImporting] = useState(false);

  const handleFiles = async (fileList: FileList) => {
    const list = Array.from(fileList);
    if (!list.length) return;
    const initial: FileState[] = list.map((f) => ({ name: f.name, status: "waiting", stage: "等待中" }));
    setFiles(initial);
    setImporting(true);

    const formData = new FormData();
    list.forEach((f) => formData.append("files", f));

    try {
      const resp = await api.import(formData);
      if (!resp.ok) throw new Error("导入失败");
      for await (const event of parseSSE(resp)) {
        const e = event as { type: string; file_id?: string; file_name?: string; status?: string; stage?: string; message?: string; total?: number; imported_files?: number; failed_files?: number };
        if (!e.file_id) {
          if (e.type === "done") break;
          continue;
        }
        setFiles((prev) =>
          prev.map((f) => {
            if (f.name !== e.file_name) return f;
            if (e.type === "stage") {
              return {
                ...f,
                status: e.status === "done" ? "done" : "running",
                stage: e.message || e.stage || "",
              };
            }
            if (e.type === "error") {
              return { ...f, status: "error", stage: e.message || `失败于 ${e.stage}` };
            }
            return f;
          })
        );
      }
    } catch {
      setFiles((prev) => prev.map((f) => (f.status === "waiting" ? { ...f, status: "error", stage: "导入失败" } : f)));
    } finally {
      setImporting(false);
      setTimeout(onClose, 1500);
    }
  };

  return (
    <div className="fixed bottom-6 left-[calc(72px+20px+16px)] w-[320px] z-[150]">
      <Card variant="elevated" className="p-4 max-h-[60vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-3">
          <span className="text-title">导入简历</span>
          <IconButton icon="close" size={18} onClick={onClose} title="关闭" />
        </div>

        {files.length === 0 ? (
          <button
            onClick={() => inputRef.current?.click()}
            className="state-layer w-full py-6 rounded-md border border-dashed border-outline text-body-sm text-on-surface-variant cursor-pointer flex flex-col items-center gap-2"
          >
            <Icon name="upload_file" size={24} />
            选择 PDF / JSONL / MD / TXT 文件
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
                    {f.status === "done" ? "完成" : f.status === "error" ? "失败" : f.status === "running" ? f.stage : "等待"}
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
          accept=".pdf,.jsonl,.md,.txt"
          multiple
          hidden
          onChange={(e) => e.target.files && handleFiles(e.target.files)}
        />
      </Card>
    </div>
  );
}
