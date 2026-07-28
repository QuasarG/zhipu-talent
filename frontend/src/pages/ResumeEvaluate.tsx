import PageToolbar from "@/components/layout/PageToolbar";

export default function ResumeEvaluate() {
  return (
    <div>
      <PageToolbar title="简历评估" subtitle="能力结构、Track 推荐与论文核验" />
      <div className="flex items-center justify-center h-[500px] text-ink-secondary">
        <div className="text-center">
          <p className="text-lg">简历评估工作台</p>
          <p className="text-sm mt-2">即将填充…</p>
        </div>
      </div>
    </div>
  );
}
