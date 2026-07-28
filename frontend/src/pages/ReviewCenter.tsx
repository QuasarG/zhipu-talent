import PageToolbar from "@/components/layout/PageToolbar";

export default function ReviewCenter() {
  return (
    <div>
      <PageToolbar title="待核验" subtitle="论文冲突、外部事实冲突与身份合并建议" />
      <div className="flex items-center justify-center h-[500px] text-ink-secondary">
        <p className="text-lg">待核验中心</p>
      </div>
    </div>
  );
}
