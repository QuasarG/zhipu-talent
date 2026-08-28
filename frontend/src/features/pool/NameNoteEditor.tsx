// 姓名备注行内编辑器：铅笔 hover 显隐，Enter 保存 / Esc 取消
import { useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import Icon from "@/components/ui/Icon";

interface Props {
  personId: string;
  nameNote: string;
  rawName: string;
  onSaved: () => void;
}

export default function NameNoteEditor({ personId, nameNote, rawName, onSaved }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const { t } = useI18n();

  const save = async () => {
    try {
      await api.persons.setNameNote(personId, draft.trim());
      setEditing(false);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("保存失败"));
    }
  };

  if (!editing) {
    return (
      <span className="inline-flex items-center gap-2 min-w-0">
        {nameNote && rawName && (
          <span className="text-body-sm text-on-surface-variant truncate">（{rawName}）</span>
        )}
        <button
          onClick={() => { setDraft(nameNote || ""); setEditing(true); }}
          className="state-layer shrink-0 inline-flex items-center justify-center h-6 w-6 rounded-full text-on-surface-variant hover:bg-surface-low opacity-60 hover:opacity-100 cursor-pointer"
          title={t("姓名备注（优先显示）")}
        >
          <Icon name="edit" size={14} />
        </button>
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") void save();
          if (e.key === "Escape") setEditing(false);
        }}
        placeholder={t("姓名备注（优先显示）")}
        className="h-8 w-44 px-2 rounded-sm border border-outline-variant bg-surface-lowest text-body-sm text-on-surface outline-none focus:outline-2 focus:outline-primary"
      />
      <button onClick={() => void save()} className="state-layer h-6 px-2 rounded-full text-label text-primary cursor-pointer">{t("保存")}</button>
      <button onClick={() => setEditing(false)} className="state-layer h-6 px-2 rounded-full text-label text-on-surface-variant cursor-pointer">{t("取消")}</button>
      {error && <span className="text-label text-error">{error}</span>}
    </span>
  );
}
