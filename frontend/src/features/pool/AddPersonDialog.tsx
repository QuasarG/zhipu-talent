import { useState } from "react";
import { api } from "@/lib/api";
import Card from "@/components/ui/Card";
import Button, { IconButton } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

interface Props {
  onClose: () => void;
  onAdded: () => void;
}

const inputClass =
  "h-9 px-3 rounded-sm border border-outline-variant bg-surface-lowest text-body-sm text-on-surface outline-none focus:outline-2 focus:outline-primary";

/** 手动加入人才库：guest 类型，进列表和图谱但不参与 Track 分类 */
export default function AddPersonDialog({ onClose, onAdded }: Props) {
  const [form, setForm] = useState({ name: "", org: "", direction: "" });
  const [adding, setAdding] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  const submit = async () => {
    const name = form.name.trim();
    if (!name || adding) return;
    setAdding(true);
    setResult(null);
    try {
      const brief = await api.persons.create({
        name,
        org: form.org.trim(),
        direction: form.direction.trim(),
      });
      setResult({ ok: true, text: `已加入人才库：${brief.name}，可在人才库「人物调查」中查看` });
      setForm({ name: "", org: "", direction: "" });
      onAdded();
    } catch (err) {
      setResult({ ok: false, text: err instanceof Error ? err.message : "加入失败" });
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-inverse-surface/30" onClick={onClose}>
      <Card variant="elevated" className="w-[400px] p-5 flex flex-col gap-3" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <p className="text-title-lg">手动加入人才库</p>
          <IconButton icon="close" onClick={onClose} title="关闭" />
        </div>
        <input
          type="text"
          value={form.name}
          onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
          placeholder="姓名（必填）"
          className={inputClass}
        />
        <input
          type="text"
          value={form.org}
          onChange={(e) => setForm((p) => ({ ...p, org: e.target.value }))}
          placeholder="学校 / 机构"
          className={inputClass}
        />
        <input
          type="text"
          value={form.direction}
          onChange={(e) => setForm((p) => ({ ...p, direction: e.target.value }))}
          placeholder="研究方向"
          className={inputClass}
        />
        <Button
          variant="tonal"
          icon="person_add"
          className="w-full"
          disabled={!form.name.trim() || adding}
          onClick={submit}
        >
          {adding ? "加入中…" : "加入人才库"}
        </Button>
        {result && (
          <p className={cn("text-label", result.ok ? "text-success" : "text-error")}>{result.text}</p>
        )}
        <p className="text-label text-on-surface-variant">以「人物调查」身份进入列表和图谱，不参与 Track 分类</p>
      </Card>
    </div>
  );
}
