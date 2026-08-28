import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { DragOverlay, useDroppable, type DragStartEvent, type DragEndEvent } from "@dnd-kit/core";
import { SortableContext, useSortable, horizontalListSortingStrategy } from "@dnd-kit/sortable";
import { api } from "@/lib/api";
import type { CandidateDetail } from "@/lib/types";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import Button from "@/components/ui/Button";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import ResumeContent, { OriginalPreview } from "@/features/resume/ResumeContent";
import NameNoteEditor from "./NameNoteEditor";
import ScoreOverview from "@/features/resume/ScoreOverview";
import Tabs from "@/components/ui/Tabs";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/cn";

interface DeckEntry {
  personId: string;
  name: string;
  detail?: CandidateDetail;
  error?: string;
}

interface Props {
  /** 左列表当前选中（点选也能一键入轨） */
  selectedId: string | null;
  personsName: (id: string) => string;
  /** 页面级 DndContext 的 onDragEnd 通过 ref 调进来（拖入即加轨） */
  deckApiRef?: RefObject<{ addToDeck: (id: string) => void } | null>;
  /** 页面级 DndContext 转发：滑轨卡自身拖拽事件（deck 内重排） */
  deckDragApiRef?: RefObject<{
    onDeckDragStart: (e: DragStartEvent) => void;
    onDeckDragEnd: (e: DragEndEvent) => void;
  } | null>;
}

/** 轨内卡的拖拽 id 加前缀：左列表行也用 personId 注册，不隔离会互相劫持激活节点 */
const deckDragId = (personId: string) => `deck:${personId}`;
const fromDragId = (dragId: string) => (dragId.startsWith("deck:") ? dragId.slice(5) : null);
/** 名字清洗：历史 sessionStorage 污染（name 被写成 id）一律视为无名 */
const realName = (name: string | undefined | null, personId: string) =>
  name && name !== personId ? name : "";

/** 简历对比滑轨（niri 风）：左列表拖入卡片，Shift+滚轮横滚，恰好同时显示两份。 */
export default function TrackDeck({ selectedId, personsName, deckApiRef, deckDragApiRef }: Props) {
  // 滑轨状态跟随：sessionStorage 存 {id, name} 顺序（刷新恢复；标签页隔离，不跨用户同步）
  // name 一并存：恢复不依赖左列表加载时机（旧结构纯 id 数组兼容读）
  const DECK_KEY = "talent-pool.deck";
  const [deck, setDeck] = useState<DeckEntry[]>(() => {
    try {
      const raw = JSON.parse(sessionStorage.getItem(DECK_KEY) || "[]") as (string | { personId: string; name: string })[];
      return raw.map((item) =>
        typeof item === "string" ? { personId: item, name: "" } : { personId: item.personId, name: item.name || "" },
      );
    } catch {
      return [];
    }
  });
  const [draggingId, setDraggingId] = useState<string | null>(null);
  // 左列表行拖起时也挂一张贴光标的小卡（列表行本体保持原样不动）
  const [listDragId, setListDragId] = useState<string | null>(null);
  // 重复放人时已有卡的提示光圈
  const [flashId, setFlashId] = useState<string | null>(null);
  // 抓取点在卡片内的偏移：让浮起的小卡贴在光标旁而不是卡片左上角
  const [grabOffset, setGrabOffset] = useState({ x: 24, y: 22 });
  const scrollRef = useRef<HTMLDivElement>(null);
  const { t } = useI18n();

  // 提示光圈一闪即灭
  useEffect(() => {
    if (!flashId) return;
    const timer = setTimeout(() => setFlashId(null), 900);
    return () => clearTimeout(timer);
  }, [flashId]);

  // deck 变更即持久化
  useEffect(() => {
    try {
      sessionStorage.setItem(DECK_KEY, JSON.stringify(deck.map((e) => ({ personId: e.personId, name: e.name }))));
    } catch {
      /* ignore */
    }
  }, [deck]);
  const load = useCallback(async (personId: string) => {
    setDeck((prev) => prev.map((e) => (e.personId === personId ? { ...e, detail: undefined, error: undefined } : e)));
    try {
      const detail = await api.personResume(personId);
      // 详情回填名字：sessionStorage 里可能只剩 id 占位名
      setDeck((prev) =>
        prev.map((e) =>
          e.personId === personId ? { ...e, detail, name: realName(detail.name, personId) || realName(e.name, personId) } : e,
        ),
      );
    } catch (err) {
      const raw = err instanceof Error ? err.message : "";
      const msg = raw.includes("没有关联简历") ? t("该人员没有关联简历档案") : raw || t("加载失败");
      setDeck((prev) => prev.map((e) => (e.personId === personId ? { ...e, error: msg } : e)));
    }
  }, [t]);

  // 刷新恢复：清洗污染名（历史 bug 会把 id 写进 name），缺的从父层补，然后懒加载详情
  const hydratedRef = useRef(false);
  useEffect(() => {
    if (hydratedRef.current || deck.length === 0) return;
    hydratedRef.current = true;
    setDeck((prev) =>
      prev.map((e) => ({
        ...e,
        name: realName(e.name, e.personId) || realName(e.detail?.name, e.personId) || realName(personsName(e.personId), e.personId),
      })),
    );
    for (const e of deck) {
      if (!e.detail && !e.error) void load(e.personId);
    }
  }, [deck, personsName, load]);

  const addToDeck = useCallback(
    (personId: string) => {
      // 已在轨：不入轨不刷新，已有卡闪一圈并平滑滚过去（不可重复放人）
      if (deck.some((e) => e.personId === personId)) {
        setFlashId(personId);
        scrollRef.current
          ?.querySelector(`[data-person-id="${personId}"]`)
          ?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
        return;
      }
      setDeck((prev) => [...prev, { personId, name: realName(personsName(personId), personId) }]);
      // 入轨即加载
      void load(personId);
      // 新卡入轨后滚到最右
      requestAnimationFrame(() => {
        const el = scrollRef.current;
        if (el) el.scrollLeft = el.scrollWidth;
      });
    },
    [deck, load, personsName],
  );

  useEffect(() => {
    if (deckApiRef) deckApiRef.current = { addToDeck };
  }, [deckApiRef, addToDeck]);

  const onDeckDragStart = useCallback((e: DragStartEvent) => {
    // 抓取点偏移：让浮起的小卡贴在光标旁而不是节点左上角
    const ae = e.activatorEvent as Partial<PointerEvent>;
    const rect = e.active.rect.current.initial;
    if (rect && typeof ae.clientX === "number" && typeof ae.clientY === "number") {
      setGrabOffset({ x: ae.clientX - rect.left, y: ae.clientY - rect.top });
    }
    const raw = String(e.active.id);
    const id = fromDragId(raw);
    if (id) {
      // 轨内卡重排（deck: 前缀隔离；此前同 id 会劫持出幻影占位框）
      if (deck.some((x) => x.personId === id)) setDraggingId(id);
    } else {
      // 左列表行：只挂贴光标的小卡，不碰轨内状态
      setListDragId(raw);
    }
  }, [deck]);

  const onDeckDragEnd = useCallback((e: DragEndEvent) => {
    const from = fromDragId(String(e.active.id));
    const to = e.over ? fromDragId(String(e.over.id)) : null;
    setDraggingId(null);
    setListDragId(null);
    if (!from) return;
    setDeck((prev) => {
      const fi = prev.findIndex((x) => x.personId === from);
      if (fi < 0) return prev;
      // 落在轨道容器空白处（非某张卡）→ 移到末尾；落出轨道 → 不动
      const ti = to == null ? (e.over?.id === "track-deck-drop" ? prev.length - 1 : -1)
        : prev.findIndex((x) => x.personId === to);
      if (ti < 0 || ti === fi) return prev;
      const next = [...prev];
      const [moved] = next.splice(fi, 1);
      next.splice(ti, 0, moved);
      return next;
    });
  }, []);

  useEffect(() => {
    if (deckDragApiRef) deckDragApiRef.current = { onDeckDragStart, onDeckDragEnd };
  }, [deckDragApiRef, onDeckDragStart, onDeckDragEnd]);


  const removeFromDeck = (personId: string) => setDeck((prev) => prev.filter((e) => e.personId !== personId));
  const clearDeck = () => setDeck([]);

  // Shift+滚轮 → 横向滚动（niri 习惯）；无 Shift 时不动，避免抢垂直滚动
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      // 触摸板横向动能（|deltaX| 大）无条件吞掉：不 preventDefault 会被 Chrome
      // 当导航手势（后退/前进）。Shift+滚轮转横向滚动。
      const trackpadHorizontal = Math.abs(e.deltaX) > Math.abs(e.deltaY);
      if (trackpadHorizontal || e.shiftKey) {
        e.preventDefault();
        el.scrollLeft += e.deltaY + e.deltaX;
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const { setNodeRef, isOver } = useDroppable({ id: "track-deck-drop" });
  const dragEntry = draggingId ? deck.find((e) => e.personId === draggingId) : undefined;
  // 展示名：详情名 > 列表实时名 > 轨道存名（任何一环是 id 占位都跳过）
  const displayName = (e: DeckEntry) =>
    realName(e.detail?.name, e.personId) || realName(personsName(e.personId), e.personId) || realName(e.name, e.personId);
  const listDragName = listDragId ? realName(personsName(listDragId), listDragId) : "";

  return (
    <Card variant="filled" className="flex flex-col min-h-0 min-w-0 flex-1 overflow-hidden">
        {/* 工具条（卡片头） */}
        <div className="flex items-center justify-between gap-2 px-3 h-11 shrink-0 border-b border-outline-variant">
          <div className="flex items-center gap-2 min-w-0">
            <Icon name="compare" size={16} className="text-primary shrink-0" />
            <span className="text-label text-on-surface-variant truncate">
              {t("对比滑轨 · 按住 Shift 滚动切换 · 从左侧拖入人才")}
            </span>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            {selectedId && (
              <Button variant="text" icon="add" className="h-7 px-2 text-xs" onClick={() => addToDeck(selectedId)}>
                {t("加入当前选中")}
              </Button>
            )}
            {deck.length > 0 && (
              <Button variant="text" icon="close" className="h-7 px-2 text-xs" onClick={clearDeck}>
                {t("清空轨道")}
              </Button>
            )}
          </div>
        </div>

        {/* 轨道体：卡片内横滚区，每卡恰好占 1/2 视宽 */}
        <div
          ref={(node) => {
            // 同一元素既是横滚容器又是拖放目标：合并两个 ref
            scrollRef.current = node;
            setNodeRef(node);
          }}
          className={cn(
            "flex-1 min-h-0 overflow-x-auto overflow-y-hidden overscroll-x-contain transition-colors",
            // 空态时容器自身就是居中布局（grid place-items 不依赖子项宽高传递）
            deck.length === 0 && "grid place-items-center",
            isOver && "bg-primary-container/40",
          )}
        >
          {deck.length === 0 ? (
            /* 空态：容器 grid 居中；svg 被 preflight 设为 block，text-center 管不住，用 flex 居中 */
            <div className="flex flex-col items-center text-center px-6">
              <Icon name="compare" size={32} className="text-on-surface-variant" />
              <p className="mt-2 text-body text-on-surface">{t("轨道为空")}</p>
              <p className="text-body-sm text-on-surface-variant">{t("从左侧列表拖动人才到这里，或点击「加入当前选中」")}</p>
            </div>
          ) : (
          <div className="flex h-full gap-3 p-3 w-max">
            <SortableContext items={deck.map((e) => deckDragId(e.personId))} strategy={horizontalListSortingStrategy}>
            {deck.map((entry) => (
                <DeckCard
                  key={entry.personId}
                  entry={entry}
                  displayName={displayName(entry)}
                  dragging={draggingId === entry.personId}
                  flash={flashId === entry.personId}
                  onRemove={() => removeFromDeck(entry.personId)}
                  onReload={load}
                  t={t}
                />
            ))}
            {/* 新卡落点预告：列表行拖到轨道上方时，末尾长出虚线框（入轨即追加到末尾） */}
            {listDragId && (
              <div
                style={{
                  width: isOver ? "calc((100vw - 24rem - 4rem) / 2)" : 0,
                  marginLeft: isOver ? 0 : -12,
                  opacity: isOver ? 1 : 0,
                  transition: "width 220ms cubic-bezier(0.2, 0, 0, 1), opacity 180ms ease-out, margin-left 220ms cubic-bezier(0.2, 0, 0, 1)",
                }}
                className="h-full shrink-0 rounded-md border-2 border-dashed border-primary/60 bg-primary-container/10 grid place-items-center overflow-hidden pointer-events-none"
              >
                <span className="text-label text-primary/70 whitespace-nowrap">{t("松手放到这里")}</span>
              </div>
            )}
            </SortableContext>
          </div>
          )}
          {/* 拖动动效：轨内卡原地淡出成虚线框，光标处弹起半透明小卡；列表行拖起只挂小卡 */}
          <DragOverlay dropAnimation={dragEntry ? { duration: 240, easing: "cubic-bezier(0.18, 0, 0.2, 1)" } : null}>
            {dragEntry ? (
              <MiniDragCard name={displayName(dragEntry)} score={dragEntry.detail?.evaluation?.overall_score} grabOffset={grabOffset} />
            ) : listDragId ? (
              <MiniDragCard name={listDragName} grabOffset={grabOffset} />
            ) : null}
          </DragOverlay>
        </div>
    </Card>
  );
}

/** 轨道内可排序卡片：仅卡头横栏可拖；拖动时真身淡出、虚线框随指针滑移 */
function DeckCard({ entry, displayName, dragging, flash, onRemove, onReload, t }: {
  entry: DeckEntry;
  displayName: string;
  dragging: boolean;
  flash: boolean;
  onRemove: () => void;
  onReload: (personId: string) => void;
  t: (k: string) => string;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isSorting } = useSortable({
    id: deckDragId(entry.personId),
    data: { type: "deck-card" },
  });
  // 让位动画：兄弟卡 spring 位移让位；被拖卡（虚线框）紧跟指针，不加过渡
  const shiftTransition = isSorting && !dragging
    ? "transform 280ms cubic-bezier(0.18, 0, 0.2, 1.12)"
    : transition;
  return (
    <section
      ref={setNodeRef}
      data-person-id={entry.personId}
      style={{
        width: "calc((100vw - 24rem - 4rem) / 2)",
        // 虚线框钳在轨道内：只吃横向位移，纵向由光标处的迷你卡自由跟随
        transform: transform
          ? `translate3d(${transform.x}px, 0px, 0)`
          : undefined,
        transition: dragging ? undefined : shiftTransition,
      }}
      className={cn(
        "relative flex flex-col h-full rounded-md border overflow-hidden shrink-0 select-none transition-shadow duration-300",
        flash && "shadow-[inset_0_0_0_2px_var(--color-primary)]",
        dragging ? "border-transparent" : "border-outline-variant bg-surface-lowest",
      )}
    >
      {/* 真身内容：拖动时快速淡出，留下虚线框占位 */}
      <div
        className={cn(
          "flex flex-col flex-1 min-h-0 transition-opacity duration-150",
          dragging && "opacity-0 pointer-events-none",
        )}
      >
        {/* 卡头横栏 = 拖拽把手：名字 + 分数 + 移除 */}
        <div
          {...attributes}
          {...listeners}
          className="flex items-center gap-2 px-3 h-10 shrink-0 border-b border-outline-variant bg-surface-low cursor-grab active:cursor-grabbing [touch-action:none] outline-none focus-visible:bg-primary-container/30"
        >
          <Icon name="drag_indicator" size={15} className="text-on-surface-variant shrink-0" />
          <span className="text-title truncate">{displayName || "…"}</span>
          <span className="ml-auto flex items-center gap-1 shrink-0">
            {entry.detail?.evaluation?.overall_score != null && (
              <span className="text-title font-bold text-primary tabular-nums">
                {entry.detail.evaluation.overall_score}
              </span>
            )}
            <button
              onClick={onRemove}
              className="state-layer w-7 h-7 rounded-full flex items-center justify-center text-on-surface-variant hover:text-error cursor-pointer"
              title={t("移出轨道")}
            >
              <Icon name="close" size={15} />
            </button>
          </span>
        </div>
        {/* 卡体：简历 / 评估结果 / 运行过程 三视图 */}
        <div className="flex-1 min-h-0 flex flex-col" onPointerDown={(e) => e.stopPropagation()}>
          {entry.error ? (
            <p className="text-body-sm text-error p-3">{entry.error}</p>
          ) : !entry.detail ? (
            <div className="flex items-center justify-center py-10">
              <LoadingIndicator size={22} strokeWidth={2.5} />
            </div>
          ) : (
            <DeckCardBody entry={entry} t={t} onRefresh={onReload} />
          )}
        </div>
      </div>
      {/* 虚线占位框：常驻 DOM 只做透明度交叉淡入，拖动时随指针在轨道内滑动 */}
      <div
        aria-hidden
        className={cn(
          "absolute inset-0 rounded-md border-2 border-dashed border-primary/60 bg-primary-container/10 grid place-items-center transition-opacity duration-150 pointer-events-none",
          dragging ? "opacity-100" : "opacity-0",
        )}
      >
        <span className="text-label text-primary/70">{t("松手放到这里")}</span>
      </div>
    </section>
  );
}

/** 贴鼠标的迷你拖影卡：弹入（scale+opacity+blur），半透明，随光标滑动 */
function MiniDragCard({ name, score, grabOffset }: { name: string; score?: number | null; grabOffset: { x: number; y: number } }) {
  // 弹入：挂载后下一帧置位，由小放大浮现，读起来像整卡收缩聚到光标上
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    let raf2 = 0;
    const raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => setSettled(true));
    });
    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
    };
  }, []);
  return (
    <div
      style={{
        // 贴光标：左缘略偏光标左侧、垂直居中于光标；叠加弹入缩放
        transform: `translate(${grabOffset.x - 20}px, ${grabOffset.y - 22}px) scale(${settled ? 1 : 0.4})`,
        opacity: settled ? 1 : 0,
        filter: settled ? "blur(0px)" : "blur(3px)",
        transition: "transform 240ms cubic-bezier(0.2, 0, 0, 1), opacity 160ms ease-out, filter 200ms ease-out",
      }}
      className="flex items-center gap-2.5 h-11 px-4 rounded-full bg-surface-lowest/85 backdrop-blur-sm border-2 border-primary/80 shadow-2 select-none"
    >
      <Icon name="drag_indicator" size={15} className="text-primary shrink-0" />
      <span className="w-7 h-7 rounded-full bg-primary-container text-on-primary-container grid place-items-center text-label font-bold shrink-0">
        {(name || "?").charAt(0)}
      </span>
      <span className="text-body font-semibold text-on-surface truncate max-w-[10rem]">{name}</span>
      {score != null && (
        <span className="text-body font-bold text-primary tabular-nums shrink-0">{score}</span>
      )}
    </div>
  );
}

/** 卡体四视图：结构化简历 / 简历原件 / 评估结果 / 运行过程
 *  （= 评估页中间卡 + 右侧工作台卡合并，tab 全部拉平） */
function DeckCardBody({ entry, t, onRefresh }: { entry: DeckEntry; t: (k: string) => string; onRefresh?: (personId: string) => void }) {
  const [tab, setTab] = useState<"structured" | "raw" | "result" | "process">("structured");
  const detail = entry.detail!;
  return (
    <>
      <Tabs
        className="px-3 pt-2 shrink-0"
        items={[
          { value: "structured", label: t("结构化简历") },
          { value: "raw", label: t("简历原件") },
          { value: "result", label: t("评估结果") },
          { value: "process", label: t("运行过程"), badge: countDone(detail) || undefined },
        ]}
        value={tab}
        onChange={(v) => setTab(v as typeof tab)}
      />
      <div className="flex-1 min-h-0 overflow-y-auto p-3">
        {tab === "structured" && (
          <ResumeContent
            detail={detail}
            hideTabs
            nameNoteEditor={detail.person_id ? (
              <NameNoteEditor
                personId={detail.person_id}
                nameNote={detail.name_note || ""}
                rawName={detail.name}
                onSaved={() => onRefresh?.(entry.personId)}
              />
            ) : undefined}
          />
        )}
        {tab === "raw" && (
          <OriginalPreview candidateId={detail.id} sourceFormat={detail.source_format} fallbackText={detail.raw_text || ""} />
        )}
        {tab === "result" &&
          (detail.evaluation ? (
            <ScoreOverview evaluation={detail.evaluation} academicReport={detail.academic_report} personId={entry.personId} />
          ) : (
            <p className="text-body-sm text-on-surface-variant">{t("尚无评估结果")}</p>
          ))}
        {tab === "process" && <DeckProcess detail={detail} t={t} />}
      </div>
    </>
  );
}

/** 运行过程轻量视图：评估图的节点按阶段分组打点（复用评估页同款状态色） */
function DeckProcess({ detail, t }: { detail: CandidateDetail; t: (k: string) => string }) {
  const runMap = new Map((detail.evaluation_run?.node_runs || []).map((r) => [r.node, r]));
  const phases = detail.evaluation_graph?.phases || [];
  const flat = phases.flatMap((ph) => ph.groups.flatMap((g) => g.nodes));
  if (!detail.evaluation_run && flat.length === 0) {
    return <p className="text-body-sm text-on-surface-variant">{t("尚无评估结果")}</p>;
  }
  return (
    <ol className="flex flex-col">
      {phases.map((phase) => (
        <li key={phase.key} className="mb-3">
          <p className="text-label font-semibold text-on-surface-variant mb-1">{t(phase.label)}</p>
          <ul>
            {phase.groups.flatMap((g) => g.nodes).map((node) => {
              const run = runMap.get(node.node);
              const status = run?.status || "pending";
              return (
                <li key={node.node} className="flex items-center gap-2 py-1">
                  <span
                    className={cn(
                      "w-1.5 h-1.5 rounded-full shrink-0",
                      status === "done" ? "bg-success" : status === "error" ? "bg-error" : status === "running" ? "bg-primary" : "bg-outline",
                    )}
                  />
                  <span className={cn("text-body-sm truncate", status === "pending" ? "text-on-surface-variant" : "text-on-surface")}>
                    {t(node.label)}
                  </span>
                  {run?.message && (
                    <span className="ml-auto text-label text-on-surface-variant truncate max-w-[50%]" title={run.message}>
                      {run.message}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </li>
      ))}
    </ol>
  );
}

function countDone(detail: CandidateDetail): number {
  const runs = detail.evaluation_run?.node_runs || [];
  return runs.filter((r) => r.status === "done" || r.status === "skipped").length;
}
