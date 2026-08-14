import { useState } from "react";
import type { TalentGroup } from "@/lib/types";
import { api } from "@/lib/api";
import Icon from "@/components/ui/Icon";
import { useI18n } from "@/lib/i18n";

interface Props {
  groups: TalentGroup[];
  onChanged: () => void;
  onClose: () => void;
}

export default function GroupDrawer({ groups, onChanged, onClose }: Props) {
  const [newName, setNewName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { t } = useI18n();

  const create = async () => {
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    try {
      await api.talentGroups.create(name);
      setNewName("");
      onChanged();
    } finally { setBusy(false); }
  };

  const rename = async (id: string) => {
    const name = editName.trim();
    if (!name) { setEditingId(null); return; }
    setBusy(true);
    try {
      await api.talentGroups.rename(id, name);
      setEditingId(null);
      onChanged();
    } finally { setBusy(false); }
  };

  const remove = async (id: string) => {
    setBusy(true);
    try {
      await api.talentGroups.delete(id);
      setConfirmingId(null);
      onChanged();
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="bg-surface rounded-lg shadow-xl w-[min(440px,92vw)] max-h-[70vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 px-5 py-3 border-b border-outline-variant shrink-0">
          <Icon name="create_new_folder" size={20} className="text-primary" />
          <h2 className="text-title font-bold text-on-surface">{t("分组管理")}</h2>
          <button onClick={onClose} className="state-layer ml-auto w-8 h-8 rounded-full flex items-center justify-center text-on-surface-variant cursor-pointer">
            <Icon name="close" size={20} />
          </button>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto p-4 flex flex-col gap-2">
          {groups.length === 0 ? (
            <p className="text-center py-6 text-body-sm text-on-surface-variant">{t("还没有分组，在下面新建一个吧")}</p>
          ) : (
            groups.map((g) => (
              <div key={g.id} className="flex items-center gap-2 px-3 py-2 rounded-md hover:bg-surface-low">
                <Icon name="folder" size={18} className="text-on-surface-variant shrink-0" />
                {editingId === g.id ? (
                  <input
                    autoFocus value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    onBlur={() => rename(g.id)}
                    onKeyDown={(e) => { if (e.key === "Enter") rename(g.id); if (e.key === "Escape") setEditingId(null); }}
                    className="flex-1 h-8 px-2 rounded-sm border border-outline bg-surface-lowest text-body-sm outline-none focus:border-primary"
                  />
                ) : (
                  <span className="flex-1 text-body text-on-surface truncate">{g.name}</span>
                )}
                <span className="text-label text-on-surface-variant">{t("{count} 人", { count: g.count })}</span>
                {confirmingId === g.id ? (
                  <>
                    <button disabled={busy} onClick={() => remove(g.id)} className="px-2 h-7 rounded-full text-label text-error hover:bg-error-container cursor-pointer">{t("确认删除")}</button>
                    <button onClick={() => setConfirmingId(null)} className="px-2 h-7 rounded-full text-label text-on-surface-variant hover:bg-surface-low cursor-pointer">{t("取消")}</button>
                  </>
                ) : (
                  <>
                    <button
                      onClick={() => { setEditingId(g.id); setEditName(g.name); }}
                      className="state-layer w-7 h-7 rounded-full flex items-center justify-center text-on-surface-variant hover:text-on-surface cursor-pointer"
                      title={t("重命名")}
                    >
                      <Icon name="edit" size={16} />
                    </button>
                    <button
                      onClick={() => setConfirmingId(g.id)}
                      className="state-layer w-7 h-7 rounded-full flex items-center justify-center text-on-surface-variant hover:text-error cursor-pointer"
                      title={t("删除分组（人才退回未分组）")}
                    >
                      <Icon name="delete" size={16} />
                    </button>
                  </>
                )}
              </div>
            ))
          )}
        </div>

        <div className="flex items-center gap-2 px-4 py-3 border-t border-outline-variant shrink-0">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") create(); }}
            placeholder={t("新建分组名称…")}
            className="flex-1 h-10 px-3 rounded-sm border border-outline-variant bg-surface-lowest text-body outline-none focus:border-primary"
          />
          <button
            disabled={busy || !newName.trim()}
            onClick={create}
            className="state-layer h-10 px-4 rounded-sm bg-primary text-on-primary text-body-sm font-medium disabled:opacity-40 cursor-pointer"
          >
            {t("新建")}
          </button>
        </div>
      </div>
    </div>
  );
}
