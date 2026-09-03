// 候选人材料文件（材料包工作区）：无包时整节不渲染——存量单简历候选人不受影响
import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import Icon from "@/components/ui/Icon";
import { RecordSection } from "@/features/resume/ResumeContent";

interface FileItem {
  file: string;
  size_kb: number;
  url: string;
}

export default function CandidateMaterials({ candidateId }: { candidateId: string }) {
  const { t } = useI18n();
  const [data, setData] = useState<{ bundle_id: string; files: FileItem[] } | null>(null);

  useEffect(() => {
    let active = true;
    fetch(`/api/talent-bundles/by-candidate/${candidateId}`)
      .then((r) => (r.ok ? r.json() : { files: [] }))
      .then((d) => { if (active && d?.files?.length) setData(d); })
      .catch(() => {});
    return () => { active = false; };
  }, [candidateId]);

  if (!data?.files.length) return null;

  return (
    <RecordSection title={t("材料文件")} icon="folder_zip" count={data.files.length} className="mb-4">
      <ul className="divide-y divide-outline-variant">
        {data.files.map((f) => (
          <li key={f.file}>
            <a
              href={f.url}
              target="_blank"
              rel="noreferrer"
              className="state-layer flex items-center gap-2 px-4 py-2.5 text-body-sm text-on-surface hover:bg-surface-low"
            >
              <Icon name="description" size={16} className="shrink-0 text-on-surface-variant" />
              <span className="min-w-0 flex-1 truncate">{f.file}</span>
              <span className="shrink-0 text-label text-on-surface-variant">{f.size_kb} KB</span>
              <Icon name="open_in_new" size={14} className="shrink-0 text-primary" />
            </a>
          </li>
        ))}
      </ul>
    </RecordSection>
  );
}
