// 人才档案的原始材料目录。新数据展示完整材料包，旧数据把唯一的简历原件
// 显式呈现为单文件目录；结构化简历和评估报告都只是这些材料的派生视图。
import { useEffect, useState } from "react";
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

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    fetch(`/api/talent-bundles/by-candidate/${candidateId}`)
      .then((r) => {
        if (!r.ok) throw new Error(t("材料目录加载失败"));
        return r.json();
      })
      .then((d) => { if (active) setData(d); })
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

      <div className="min-h-0 flex-1 overflow-y-auto p-5 admission-panel-scrollbar">
        {error ? (
          <div className="flex items-center gap-2 rounded-md bg-error-container px-4 py-3 text-body-sm text-on-error-container">
            <Icon name="error" size={17} />
            {error}
          </div>
        ) : data?.files.length ? (
          <ul className="grid grid-cols-1 gap-2 2xl:grid-cols-2">
            {data.files.map((file) => {
              const isResume = file.file === data.resume_file || data.storage_kind === "legacy_resume";
              const parts = file.file.replaceAll("\\", "/").split("/");
              const name = parts.pop() || file.file;
              const location = parts.join(" / ");
              return (
                <li key={file.file}>
                  <a
                    href={file.url}
                    target="_blank"
                    rel="noreferrer"
                    className="group flex min-h-20 items-center gap-3 rounded-md border border-outline-variant bg-surface-lowest px-4 py-3 transition-colors hover:border-primary/50 hover:bg-surface-low focus-visible:outline-2 focus-visible:outline-primary"
                  >
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-sm bg-surface-high text-primary">
                      <Icon name={fileIcon(name)} size={20} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-body font-medium text-on-surface">{name}</span>
                        {isResume && <StatusChip tone="primary">{t("主简历")}</StatusChip>}
                      </span>
                      <span className="mt-1 block truncate text-label text-on-surface-variant">
                        {location || t("目录根级")} · {file.size_kb} KB
                      </span>
                    </span>
                    <Icon name="open_in_new" size={16} className="shrink-0 text-on-surface-variant transition-colors group-hover:text-primary" />
                  </a>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="flex min-h-48 flex-col items-center justify-center gap-2 rounded-md border border-dashed border-outline-variant px-6 text-center text-on-surface-variant">
            <Icon name="folder_off" size={30} />
            <p className="text-body font-medium text-on-surface">{t("目录里还没有可用材料")}</p>
            <p className="text-body-sm">{t("重新导入简历或上传一人一包的材料目录")}</p>
          </div>
        )}
      </div>
    </div>
  );
}

function fileIcon(name: string): string {
  const suffix = name.toLowerCase().split(".").pop();
  if (suffix === "pdf") return "picture_as_pdf";
  if (["png", "jpg", "jpeg", "webp"].includes(suffix || "")) return "image";
  if (["doc", "docx"].includes(suffix || "")) return "article";
  return "description";
}
