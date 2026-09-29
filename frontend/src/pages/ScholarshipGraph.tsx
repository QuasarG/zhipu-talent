import PageToolbar from "@/components/layout/PageToolbar";
import Card from "@/components/ui/Card";
import AdvisorGraph from "@/features/scholarship/AdvisorGraph";
import { useI18n } from "@/lib/i18n";

export default function ScholarshipGraph() {
  const { t } = useI18n();
  return (
    <div className="flex h-[calc(100vh-48px)] min-h-[560px] min-w-0 flex-col">
      <PageToolbar title={t("师生图谱")} subtitle={t("学校、导师与学生关系")} />
      <Card variant="filled" className="min-h-0 flex-1 overflow-hidden">
        <AdvisorGraph />
      </Card>
    </div>
  );
}
