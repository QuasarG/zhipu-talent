import { useCallback, useEffect, useRef, useState, type RefObject } from "react";
import { DragOverlay, useDroppable, type DragStartEvent, type DragEndEvent } from "@dnd-kit/core";
import { restrictToHorizontalAxis } from "@dnd-kit/modifiers";
import { SortableContext, useSortable, horizontalListSortingStrategy } from "@dnd-kit/sortable";
import { api } from "@/lib/api";
import type { CandidateDetail } from "@/lib/types";
import Card from "@/components/ui/Card";
import Icon from "@/components/ui/Icon";
import Button from "@/components/ui/Button";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import ResumeContent from "@/features/resume/ResumeContent";
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
  deckDragApiRef?: RefObject<{ onDeckDragStart: (e: DragStartEvent) => void; onDeckDragEnd: (e: DragEndEvent) => void } | null>;
}

/** 简历对比滑轨（niri 风）：左列表拖入卡片，Shift+滚轮横滚，恰好同时显示两份。 */
export default function TrackDeck({ selectedId, personsName, deckApiRef, deckDragApiRef }: Props) {
  // 滑轨状态跟随：sessionStorage 存 personId 顺序（刷新恢复；标签页隔离，不跨用户同步）
  const DECK_KEY = "talent-pool.deck";
  const [deck, setDeck] = useState<DeckEntry[]>(() => {
    try {
      const ids = JSON.parse(sessionStorage.getItem(DECK_KEY) || "[]") as string[];
      return ids.map((id) => ({ personId: id, name: "" }));
    } catch {
      return [];
    }
  });
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const { t } = useI18n();

  // deck 变更即持久化
  useEffect(() => {
    try {
      sessionStorage.setItem(DECK_KEY, JSON.stringify(deck.map((e) => e.personId)));
    } catch {
      /* ignore */
    }
  }, [deck]);
  const load = useCallback(async (personId: string) => {
    setDeck((prev) => prev.map((e) => (e.personId === personId ? { ...e, detail: undefined, error: undefined } : e)));
    try {
      const detail = await api.personResume(personId);
      setDeck((prev) => prev.map((e) => (e.personId === personId ? { ...e, detail } : e)));
    } catch (err) {
      const raw = err instanceof Error ? err.message : "";
      const msg = raw.includes("没有关联简历") ? t("该人员没有关联简历档案") : raw || t("加载失败");
      setDeck((prev) => prev.map((e) => (e.personId === personId ? { ...e, error: msg } : e)));
    }
  }, [t]);

  // 刷新恢复：补名字 + 懒加载详情（personsName 由父层传入，恢复时列表已就位）
  const hydratedRef = useRef(false);
  useEffect(() => {
    if (hydratedRef.current || deck.length === 0) return;
    hydratedRef.current = true;
    setDeck((prev) => prev.map((e) => ({ ...e, name: e.name || personsName(e.personId) })));
    for (const e of deck) {
      if (!e.detail && !e.error) void load(e.personId);
    }
  }, [deck, personsName, load]);

  const addToDeck = useCallback(
    (personId: string) => {
      setDeck((prev) => {
        if (prev.some((e) => e.personId === personId)) return prev; // 去重
        return [...prev, { personId, name: personsName(personId) }];
      });
      // 入轨即加载（重复添加时也刷新）
      void load(personId);
      // 新卡入轨后滚到最右
      requestAnimationFrame(() => {
        const el = scrollRef.current;
        if (el) el.scrollLeft = el.scrollWidth;
      });
    },
    [load, personsName],
  );

  useEffect(() => {
    if (deckApiRef) deckApiRef.current = { addToDeck };
  }, [deckApiRef, addToDeck]);

  const onDeckDragStart = useCallback((e: DragStartEvent) => {
    setDraggingId(String(e.active.id));
  }, []);

  const onDeckDragEnd = useCallback((e: DragEndEvent) => {
    setDraggingId(null);
    const from = String(e.active.id);
    const to = e.over ? String(e.over.id) : "";
    if (!to || from === to) return;
    // deck 内重排：把 from 移到 to 的位置
    setDeck((prev) => {
      const fi = prev.findIndex((x) => x.personId === from);
      const ti = prev.findIndex((x) => x.personId === to);
      if (fi < 0 || ti < 0) return prev;
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
            /* 空态：容器 grid 居中，内容块只管排字 */
            <div className="text-center px-6">
              <Icon name="compare" size={32} className="text-on-surface-variant" />
              <p className="mt-2 text-body text-on-surface">{t("轨道为空")}</p>
              <p className="text-body-sm text-on-surface-variant">{t("从左侧列表拖动人才到这里，或点击「加入当前选中」")}</p>
            </div>
          ) : (
          <div className="flex h-full gap-3 p-3 w-max">
            <SortableContext items={deck.map((e) => e.personId)} strategy={horizontalListSortingStrategy}>
            {deck.map((entry) => (
                <DeckCard
                  key={entry.personId}
                  entry={entry}
                  dragging={draggingId === entry.personId}
                  onRemove={() => removeFromDeck(entry.personId)}
                  t={t}
                />
            ))}
            </SortableContext>
          </div>
          )}
          {/* 拖动动效：浮起卡影跟随指针（真身在原地半透明占位） */}
          <DragOverlay
            // 跟随是 spring（modifiers 由 dnd-kit 内建约束）
            modifiers={[restrictToHorizontalAxis]}
            dropAnimation={null}
          >
            {draggingId ? (
              <DeckCardGhost entry={deck.find((e) => e.personId === draggingId)!} />
            ) : null}
          </DragOverlay>
        </div>
    </Card>
  );
}

/** 轨道内可排序卡片 */
function DeckCard({ entry, dragging, onRemove, t }: {
  entry: DeckEntry;
  dragging: boolean;
  onRemove: () => void;
  t: (k: string) => string;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isSorting } = useSortable({
    id: entry.personId,
    data: { type: "deck-card" },
  });
  // 让位动画：spring（弹性位移）替代默认 linear，松手回弹有生命感
  const springTransition = isSorting
    ? "transform 260ms cubic-bezier(0.18, 0, 0.2, 1.2)"
    : transition;
  return (
                <section
                  ref={setNodeRef}
                  {...attributes}
                  {...listeners}
                  style={{
                    width: "calc((100vw - 24rem - 4rem) / 2)",
                    transform: transform
                      ? `translate3d(${transform.x}px, ${transform.y}px, 0)`
                      : undefined,
                    transition: springTransition,
                  }}
                  className={cn(
                    "relative flex flex-col h-full rounded-md border overflow-hidden shrink-0 select-none transition-[opacity,scale,border-color] duration-300 ease-emphasized",
                    dragging
                      ? "opacity-0 scale-90 border-primary bg-primary-container/30 pointer-events-none"
                      : "border-outline-variant bg-surface-lowest cursor-grab active:cursor-grabbing",
                  )}
                >
                  {/* 卡头：名字 + 分数 + 移除 */}
                  <div className="flex items-center gap-2 px-3 h-10 shrink-0 border-b border-outline-variant bg-surface-low">
                    <span className="text-title truncate">{entry.name}</span>
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
                  {/* 卡体：结构化简历/原件 Tabs（复用评估页） */}
                  <div className="flex-1 min-h-0 overflow-y-auto p-3" onPointerDown={(e) => e.stopPropagation()}>
                    {entry.error ? (
                      <p className="text-body-sm text-error">{entry.error}</p>
                    ) : !entry.detail ? (
                      <div className="flex items-center justify-center py-10">
                        <LoadingIndicator size={22} strokeWidth={2.5} />
                      </div>
                    ) : (
                      <ResumeContent detail={entry.detail} />
                    )}
                  </div>
                </section>
  );
}

/** DragOverlay 的浮起影子卡（只渲染头部骨架，轻量跟随） */
function DeckCardGhost({ entry }: { entry: DeckEntry }) {
  return (
    <div
      style={{ width: "calc((100vw - 24rem - 4rem) / 2)" }}
      className="h-24 rounded-md border-2 border-dashed border-primary bg-primary-container/20 backdrop-blur-[2px] grid place-items-center"
    >
      <div className="flex items-center gap-2 text-primary">
        <Icon name="drag_indicator" size={18} />
        <span className="text-body-sm font-semibold truncate max-w-[60%]">{entry.name}</span>
      </div>
    </div>
  );
}
