import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { PersonBrief, ReputationReport } from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import { StatusChip } from "@/components/ui/Chip";
import Icon from "@/components/ui/Icon";
import SegmentedButtons from "@/components/ui/SegmentedButtons";

interface ReviewItem {
  person: PersonBrief;
  report: ReputationReport;
}

type Filter = "all" | "pending" | "done";

const levelMeta: Record<string, { tone: "error" | "warning" | "success"; label: string }> = {
  red: { tone: "error", label: "红色预警" },
  yellow: { tone: "warning", label: "黄色关注" },
  green: { tone: "success", label: "绿色安全" },
};

const statusMeta: Record<string, { tone: "warning" | "success" | "neutral"; label: string; icon: string }> = {
  pending: { tone: "warning", label: "待核验", icon: "pending" },
  confirmed: { tone: "success", label: "已通过", icon: "check_circle" },
  dismissed: { tone: "neutral", label: "已驳回", icon: "cancel" },
};

function formatTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export default function ReviewCenter() {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>("all");
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [submitting, setSubmitting] = useState<number | null>(null);

  // 人物列表 → 并发拉取各人舆情报告 → 扁平汇总
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const persons = await api.persons.list();
      const results = await Promise.allSettled(persons.map((p) => api.persons.reputation(p.id)));
      const merged: ReviewItem[] = [];
      results.forEach((res, i) => {
        if (res.status !== "fulfilled") return;
        res.value.forEach((report) => merged.push({ person: persons[i], report }));
      });
      merged.sort((a, b) => (b.report.created_at || "").localeCompare(a.report.created_at || ""));
      setItems(merged);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const counts = useMemo(
    () => ({
      pending: items.filter((i) => i.report.review_status === "pending").length,
      confirmed: items.filter((i) => i.report.review_status === "confirmed").length,
      dismissed: items.filter((i) => i.report.review_status === "dismissed").length,
    }),
    [items]
  );

  const visible = useMemo(() => {
    if (filter === "pending") return items.filter((i) => i.report.review_status === "pending");
    if (filter === "done") return items.filter((i) => i.report.review_status !== "pending");
    return items;
  }, [items, filter]);

  const submitReview = async (reportId: number, action: "confirmed" | "dismissed") => {
    setSubmitting(reportId);
    try {
      await api.reputation.review(reportId, action, "工作台复核", notes[reportId] ?? "");
      await load();
    } catch (err) {
      console.error(err);
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <div>
      <PageToolbar
        title="待核验"
        subtitle="外部事实与舆情报告核验"
        right={
          <Button variant="tonal" icon="refresh" onClick={load} disabled={loading}>
            刷新
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <StatusChip tone="warning" icon="pending">待核验 {counts.pending}</StatusChip>
        <StatusChip tone="success" icon="check_circle">已通过 {counts.confirmed}</StatusChip>
        <StatusChip tone="neutral" icon="cancel">已驳回 {counts.dismissed}</StatusChip>
        <SegmentedButtons
          className="ml-auto"
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: "全部" },
            { value: "pending", label: "待核验" },
            { value: "done", label: "已处理" },
          ]}
        />
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-24 text-body-sm text-on-surface-variant">
          加载中…
        </div>
      ) : visible.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 py-24">
          <Icon name="verified" size={64} className="text-primary" />
          <p className="text-title">没有待核验的项目</p>
          <p className="text-body-sm text-on-surface-variant">新的外部事实与舆情报告会出现在这里</p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {visible.map(({ person, report }) => {
            const level = levelMeta[report.level] ?? levelMeta.green;
            const status = statusMeta[report.review_status] ?? statusMeta.pending;
            const isPending = report.review_status === "pending";
            const busy = submitting === report.id;
            return (
              <Card key={report.id} variant="filled" className="p-4">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-title">{person.name}</span>
                  <StatusChip tone={level.tone}>{level.label}</StatusChip>
                  <span className="text-body-sm text-on-surface-variant">
                    {person.org} · {formatTime(report.created_at)}
                  </span>
                  <StatusChip tone={status.tone} icon={status.icon} className="ml-auto">
                    {status.label}
                  </StatusChip>
                </div>

                <div className="mt-3 flex flex-col gap-1.5">
                  {report.events.length === 0 ? (
                    <p className="text-body-sm text-on-surface-variant">未发现公开负面事件</p>
                  ) : (
                    report.events.map((ev, idx) => (
                      <div key={idx} className="flex items-baseline gap-2 text-body-sm">
                        <span className="shrink-0 text-label px-1.5 py-0.5 rounded-xs bg-surface-high text-on-surface-variant">
                          {String(ev.category ?? "事件")}
                        </span>
                        <span className="text-on-surface">{String(ev.summary ?? "")}</span>
                        {Boolean(ev.publish_date) && (
                          <span className="shrink-0 text-label text-on-surface-variant">
                            {String(ev.publish_date)}
                          </span>
                        )}
                      </div>
                    ))
                  )}
                </div>

                {isPending ? (
                  <div className="mt-3 flex items-center gap-2">
                    <input
                      type="text"
                      value={notes[report.id] ?? ""}
                      onChange={(e) => setNotes((prev) => ({ ...prev, [report.id]: e.target.value }))}
                      placeholder="备注（可选）"
                      className="flex-1 h-10 px-3 rounded-sm border border-outline bg-transparent text-body-sm outline-none focus:border-primary placeholder:text-on-surface-variant"
                    />
                    <Button
                      variant="filled"
                      icon="check"
                      disabled={busy}
                      onClick={() => submitReview(report.id, "confirmed")}
                    >
                      通过
                    </Button>
                    <Button
                      variant="outlined"
                      icon="close"
                      disabled={busy}
                      onClick={() => submitReview(report.id, "dismissed")}
                    >
                      驳回
                    </Button>
                  </div>
                ) : (
                  (report.reviewer || report.review_note) && (
                    <p className="mt-3 text-label text-on-surface-variant">
                      {report.reviewer && `复核人：${report.reviewer}`}
                      {report.reviewer && report.review_note && " · "}
                      {report.review_note && `备注：${report.review_note}`}
                      {report.reviewed_at && ` · ${formatTime(report.reviewed_at)}`}
                    </p>
                  )
                )}
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
