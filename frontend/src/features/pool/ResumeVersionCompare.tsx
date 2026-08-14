import { useEffect, useState } from "react";
import type { ResumeVersionEntry } from "@/lib/types";
import { api } from "@/lib/api";
import Icon from "@/components/ui/Icon";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import { useI18n } from "@/lib/i18n";

interface Props {
  personId: string;
  onClose: () => void;
}

/** 从 structured 里提取列表字段为字符串数组（兼容 dict/str 混合） */
function extractList(structured: Record<string, unknown>, key: string): string[] {
  const raw = structured[key];
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    if (typeof item === "string") return item;
    if (typeof item === "object" && item !== null) {
      const obj = item as Record<string, unknown>;
      return String(obj.title || obj.school || obj.name ||
        [obj.organization, obj.role].filter(Boolean).join(" ") || JSON.stringify(item));
    }
    return String(item);
  });
}

/** 计算两列表的 diff */
function diffLists(a: string[], b: string[]) {
  const setA = new Set(a.map((s) => s.toLowerCase().trim()));
  const setB = new Set(b.map((s) => s.toLowerCase().trim()));
  return {
    added: b.filter((s) => !setA.has(s.toLowerCase().trim())),
    removed: a.filter((s) => !setB.has(s.toLowerCase().trim())),
  };
}

const FIELDS: { key: string; label: string; icon: string }[] = [
  { key: "publications", label: "论文", icon: "menu_book" },
  { key: "education", label: "教育", icon: "school" },
  { key: "experiences", label: "经历", icon: "work" },
  { key: "projects", label: "项目", icon: "construction" },
  { key: "skills", label: "技能", icon: "bolt" },
];

/** 后端 SQLite 存 UTC（isoformat 无时区后缀），补 Z 后缀按 UTC 解析，避免 8h 偏差 */
function fmtDate(iso: string): string {
  if (!iso) return "";
  const normalized = iso.includes("T") ? iso : iso.replace(" ", "T");
  const d = new Date(normalized.endsWith("Z") ? normalized : normalized + "Z");
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function ResumeVersionModal({ personId, onClose }: Props) {
  const [versions, setVersions] = useState<ResumeVersionEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [idxA, setIdxA] = useState(0);
  const [idxB, setIdxB] = useState(1);
  const { t } = useI18n();

  useEffect(() => {
    setLoading(true);
    api.persons.resumeVersions(personId)
      .then((v) => {
        setVersions(v);
        if (v.length >= 2) { setIdxA(0); setIdxB(1); }
      })
      .catch(() => setVersions([]))
      .finally(() => setLoading(false));
  }, [personId]);

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="bg-surface rounded-lg shadow-xl w-[min(900px,92vw)] max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="flex items-center gap-2 px-5 py-3 border-b border-outline-variant shrink-0">
          <Icon name="history" size={20} className="text-primary" />
          <h2 className="text-title font-bold text-on-surface">{t("简历版本对比")}</h2>
          {!loading && versions.length > 0 && (
            <span className="text-label text-on-surface-variant">{t("{count} 个版本", { count: versions.length })}</span>
          )}
          <button
            type="button"
            onClick={onClose}
            className="state-layer ml-auto inline-flex items-center justify-center w-8 h-8 rounded-full text-on-surface-variant hover:text-on-surface cursor-pointer"
          >
            <Icon name="close" size={20} />
          </button>
        </div>

        {/* 内容 */}
        <div className="flex-1 min-h-0 overflow-y-auto p-5">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <LoadingIndicator size={28} label={t("加载简历版本…")} />
            </div>
          ) : versions.length === 0 ? (
            <p className="text-center py-12 text-body-sm text-on-surface-variant">{t("暂无简历版本数据")}</p>
          ) : versions.length === 1 ? (
            <p className="text-center py-12 text-body-sm text-on-surface-variant">
              {t("仅 1 个版本（{name}），导入更多简历后可对比差异。", { name: versions[0].filename || t("未命名") })}
            </p>
          ) : (
            <>
              {/* 版本选择器 */}
              <div className="grid grid-cols-2 gap-4 mb-5">
                <div>
                  <label className="block text-label font-medium text-on-surface-variant mb-1">{t("版本 A（旧）")}</label>
                  <select
                    value={idxA}
                    onChange={(e) => setIdxA(Number(e.target.value))}
                    className="w-full rounded-sm border border-outline-variant bg-surface-lowest px-3 py-2 text-body-sm text-on-surface outline-none focus:outline-2 focus:outline-primary"
                  >
                    {versions.map((v, i) => (
                      <option key={v.submission_id} value={i}>
                        {t("{name} · {date}", { name: v.filename || t("未命名"), date: fmtDate(v.created_at) })}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-label font-medium text-on-surface-variant mb-1">{t("版本 B（新）")}</label>
                  <select
                    value={idxB}
                    onChange={(e) => setIdxB(Number(e.target.value))}
                    className="w-full rounded-sm border border-outline-variant bg-surface-lowest px-3 py-2 text-body-sm text-on-surface outline-none focus:outline-2 focus:outline-primary"
                  >
                    {versions.map((v, i) => (
                      <option key={v.submission_id} value={i}>
                        {t("{name} · {date}", { name: v.filename || t("未命名"), date: fmtDate(v.created_at) })}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Diff 区 */}
              <div className="flex flex-col gap-3">
                {FIELDS.map(({ key, label, icon }) => {
                  const va = versions[idxA];
                  const vb = versions[idxB];
                  const listA = extractList(va.structured, key);
                  const listB = extractList(vb.structured, key);
                  if (listA.length === 0 && listB.length === 0) return null;
                  const diff = diffLists(listA, listB);
                  const hasChange = diff.added.length > 0 || diff.removed.length > 0;
                  return (
                    <div key={key} className="border border-outline-variant rounded-md overflow-hidden">
                      <div className="flex items-center gap-2 px-3 py-2 bg-surface-low border-b border-outline-variant">
                        <Icon name={icon} size={16} className="text-primary" />
                        <span className="text-body-sm font-bold text-on-surface">{t(label)}</span>
                        <span className="text-label text-on-surface-variant ml-auto">
                          A:{listA.length} → B:{listB.length}
                          {hasChange && (
                            <span className="ml-2">
                              {diff.added.length > 0 && <span className="text-success">+{diff.added.length}</span>}
                              {diff.removed.length > 0 && <span className="text-error ml-1">-{diff.removed.length}</span>}
                            </span>
                          )}
                        </span>
                      </div>
                      {hasChange ? (
                        <div className="px-3 py-2 flex flex-col gap-1">
                          {diff.added.map((item, i) => (
                            <div key={`add-${i}`} className="flex items-start gap-2 text-body-sm">
                              <Icon name="add_circle" size={14} className="text-success mt-0.5 shrink-0" />
                              <span className="text-success">{item}</span>
                            </div>
                          ))}
                          {diff.removed.map((item, i) => (
                            <div key={`rm-${i}`} className="flex items-start gap-2 text-body-sm">
                              <Icon name="remove" size={14} className="text-error mt-0.5 shrink-0" />
                              <span className="text-error line-through">{item}</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="px-3 py-2 text-body-sm text-on-surface-variant">{t("无变化")}</div>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
