// 人才档案的原始材料目录。新数据展示完整材料包，旧数据把唯一的简历原件
// 显式呈现为单文件目录；结构化简历和评估报告都只是这些材料的派生视图。
import { useEffect, useMemo, useState } from "react";
import { useI18n } from "@/lib/i18n";
import Icon from "@/components/ui/Icon";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import { StatusChip } from "@/components/ui/Chip";

interface FileItem {
  file: string;
  size_kb: number;
  url: string;
}

interface MaterialsData {
  bundle_id: string | null;
  storage_kind?: "legacy_resume" | "material_bundle";
  status?: string;
  resume_file?: string;
  files: FileItem[];
}

export default function CandidateMaterials({ candidateId }: { candidateId: string }) {
  const { t } = useI18n();
  const [data, setData] = useState<MaterialsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedFile, setSelectedFile] = useState<string | null>(null);

  const activeFile = useMemo(() => {
    if (!data?.files.length) return null;
    return data.files.find((file) => file.file === selectedFile)
      || data.files.find((file) => file.file === data.resume_file)
      || data.files[0];
  }, [data, selectedFile]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    fetch(`/api/talent-bundles/by-candidate/${candidateId}`)
      .then((r) => {
        if (!r.ok) throw new Error(t("材料目录加载失败"));
        return r.json();
      })
      .then((d) => {
        if (!active) return;
        setData(d);
        setSelectedFile(d.resume_file || d.files[0]?.file || null);
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : t("材料目录加载失败"));
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [candidateId, t]);

  if (loading) {
    return <div className="flex h-full min-h-48 items-center justify-center"><LoadingIndicator size={28} label={t("正在读取材料目录…")} /></div>;
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <header className="shrink-0 border-b border-outline-variant px-5 pb-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="flex h-10 w-10 items-center justify-center rounded-md bg-primary-container text-on-primary-container">
                <Icon name="folder_open" size={22} />
              </span>
              <div>
                <h2 className="text-headline font-bold text-on-surface">{t("材料目录")}</h2>
                <p className="mt-0.5 text-body-sm text-on-surface-variant">
                  {data?.storage_kind === "material_bundle"
                    ? t("评估 Agent 只从这个候选人的目录读取证据")
                    : t("历史档案：当前目录只有一份简历原件")}
                </p>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <StatusChip tone={data?.storage_kind === "material_bundle" ? "info" : "neutral"}>
              {data?.storage_kind === "material_bundle" ? t("材料包") : t("单份历史简历")}
            </StatusChip>
            <span className="text-label tabular-nums text-on-surface-variant">
              {t("{n} 个文件", { n: data?.files.length || 0 })}
            </span>
          </div>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden xl:grid-cols-[minmax(230px,0.72fr)_minmax(0,1.7fr)]">
        {error ? (
          <div className="m-5 flex items-center gap-2 rounded-md bg-error-container px-4 py-3 text-body-sm text-on-error-container xl:col-span-2">
            <Icon name="error" size={17} />
            {error}
          </div>
        ) : data?.files.length ? (
          <>
            <aside className="min-h-0 overflow-y-auto border-b border-outline-variant bg-surface-low/45 p-3 admission-panel-scrollbar xl:border-b-0 xl:border-r">
              <div className="mb-2 flex items-center justify-between px-1">
                <span className="text-label font-semibold text-on-surface">{t("目录文件")}</span>
                <span className="text-label tabular-nums text-on-surface-variant">{data.files.length}</span>
              </div>
              <ul className="space-y-1">
                {data.files.map((file) => {
                  const isResume = file.file === data.resume_file || data.storage_kind === "legacy_resume";
                  const name = file.file.replaceAll("\\", "/").split("/").pop() || file.file;
                  const selected = file.file === activeFile?.file;
                  return (
                    <li key={file.file}>
                      <button
                        type="button"
                        onClick={() => setSelectedFile(file.file)}
                        className={`group flex w-full items-center gap-2.5 rounded-md px-2.5 py-2.5 text-left transition-colors focus-visible:outline-2 focus-visible:outline-primary ${selected ? "bg-secondary-container text-on-secondary-container" : "text-on-surface hover:bg-surface-lowest"}`}
                        aria-current={selected ? "page" : undefined}
                      >
                        <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-sm ${selected ? "bg-surface-lowest text-primary" : "bg-surface-high text-on-surface-variant"}`}>
                          <Icon name={fileIcon(name)} size={17} />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-1.5">
                            <span className="truncate text-body-sm font-medium">{name}</span>
                            {isResume && <span className="shrink-0 text-[10px] font-semibold">{t("主简历")}</span>}
                          </span>
                          <span className="mt-0.5 block truncate text-label opacity-75">{file.size_kb} KB</span>
                        </span>
                        {selected && <Icon name="chevron_right" size={16} className="shrink-0" />}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </aside>
            <MaterialPreview file={activeFile} />
          </>
        ) : (
          <div className="m-5 flex min-h-48 flex-col items-center justify-center gap-2 rounded-md border border-dashed border-outline-variant px-6 text-center text-on-surface-variant xl:col-span-2">
            <Icon name="folder_off" size={30} />
            <p className="text-body font-medium text-on-surface">{t("目录里还没有可用材料")}</p>
            <p className="text-body-sm">{t("重新导入简历或上传一人一包的材料目录")}</p>
          </div>
        )}
      </div>
    </div>
  );
}

function MaterialPreview({ file }: { file: FileItem | null }) {
  const { t } = useI18n();
  if (!file) return null;
  const name = file.file.replaceAll("\\", "/").split("/").pop() || file.file;
  const suffix = name.toLowerCase().split(".").pop() || "";
  const isImage = ["png", "jpg", "jpeg", "webp"].includes(suffix);
  const isEmbeddable = isImage || suffix === "pdf" || suffix === "txt" || suffix === "md";

  return (
    <section className="flex min-h-0 min-w-0 flex-col bg-surface-lowest" aria-label={t("文件预览")}>
      <div className="flex shrink-0 items-center gap-2 border-b border-outline-variant px-4 py-2.5">
        <Icon name={fileIcon(name)} size={17} className="text-primary" />
        <span className="min-w-0 flex-1 truncate text-body-sm font-medium text-on-surface">{name}</span>
        <span className="text-label text-on-surface-variant">{file.size_kb} KB</span>
        <a href={file.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-label font-medium text-primary hover:underline">
          <Icon name="open_in_new" size={14} />
          {t("新窗口")}
        </a>
      </div>
      <div className="relative min-h-0 flex-1 overflow-hidden bg-surface-low/30">
        {isImage ? (
          <div className="h-full overflow-auto p-6 text-center"><img src={file.url} alt={name} className="mx-auto max-h-full max-w-full rounded-sm shadow-sm" /></div>
        ) : isEmbeddable ? (
          <iframe src={file.url} title={name} className="h-full w-full bg-surface-lowest" />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center text-on-surface-variant">
            <Icon name="visibility_off" size={30} />
            <p className="text-body font-medium text-on-surface">{t("此文件类型暂不支持内嵌预览")}</p>
            <p className="max-w-sm text-body-sm">{t("Agent 仍可从材料目录读取该文件，打开新窗口查看原件")}</p>
            <a href={file.url} target="_blank" rel="noreferrer" className="text-body-sm font-medium text-primary hover:underline">{t("打开原件")}</a>
          </div>
        )}
      </div>
    </section>
  );
}

function fileIcon(name: string): string {
  const suffix = name.toLowerCase().split(".").pop();
  if (suffix === "pdf") return "picture_as_pdf";
  if (["png", "jpg", "jpeg", "webp"].includes(suffix || "")) return "image";
  if (["doc", "docx"].includes(suffix || "")) return "article";
  return "description";
}
