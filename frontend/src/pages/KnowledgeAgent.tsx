import PageToolbar from "@/components/layout/PageToolbar";

export default function KnowledgeAgent() {
  return (
    <div>
      <PageToolbar title="人才知识" subtitle="库内优先 · 必要时联网调查" />
      <div className="flex items-center justify-center h-[500px] text-ink-secondary">
        <p className="text-lg">人才知识 Agent 对话</p>
      </div>
    </div>
  );
}
