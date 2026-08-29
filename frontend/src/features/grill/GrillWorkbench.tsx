/** 画像澄清工作台（grill）：四栏布局 = 会话侧栏 + 对话流 + 提问大纲 + 画像卡。
 * 移植自 grill App.tsx，作为 TalentChat 的「画像澄清」模式视图。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, parseSSE } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type {
  GrillChatMessage as ChatMessage,
  GrillChatSegment as ChatSegment,
  GrillDeliverables as Deliverables,
  GrillOutlineNode as OutlineNode,
  GrillProfileCard as ProfileCard,
  GrillSessionSummary,
  GrillSessionState,
  GrillStoredMessage as StoredMessage,
} from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import Button from "@/components/ui/Button";
import Icon from "@/components/ui/Icon";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import SegmentedButtons from "@/components/ui/SegmentedButtons";
import ChatInput from "./ChatInput";
import AssistantMessage from "./AssistantMessage";
import SessionSidebar from "./SessionSidebar";
import OutlinePanel from "./OutlinePanel";
import ProfileCardPanel from "./ProfileCardPanel";
import DeliverablesPanel from "./DeliverablesPanel";

export type ChatMode = "qa" | "clarify";

interface SseEvent {
  type: string;
  payload: Record<string, unknown>;
}

/** 历史消息（文本 + 工具记录）→ segments 渲染模型 */
function storedToSegments(m: StoredMessage): ChatSegment[] {
  if (m.segments?.length) return m.segments.map((segment) => ({ ...segment }));
  const segments: ChatSegment[] = [];
  if (m.text.trim()) segments.push({ type: "text", text: m.text });
  (m.tools || []).forEach((t, i) =>
    segments.push({
      type: "tool",
      call_id: `hist-${i}-${t.tool}`,
      tool: t.tool,
      label: t.label,
      status: t.status === "ok" ? "ok" : "error",
      summary: t.summary,
      detail: t.detail,
    })
  );
  return segments;
}

/** 逐事件更新正在流式生成的 assistant 消息（按 call_id 匹配工具卡片） */
function applyEvent(msg: ChatMessage, e: SseEvent): ChatMessage {
  const segments = [...msg.segments];
  const p = e.payload as {
    text?: string; call_id?: string; tool?: string; label?: string;
    args_summary?: string; status?: string; summary?: string; detail?: string; message?: string;
  };
  switch (e.type) {
    case "thinking_delta": {
      const last = segments[segments.length - 1];
      if (last?.type === "thinking") {
        segments[segments.length - 1] = { ...last, text: last.text + (p.text || "") };
      } else {
        segments.push({ type: "thinking", text: p.text || "" });
      }
      return { ...msg, segments };
    }
    case "answer_delta": {
      const last = segments[segments.length - 1];
      if (last?.type === "text") {
        segments[segments.length - 1] = { ...last, text: last.text + (p.text || "") };
      } else {
        segments.push({ type: "text", text: p.text || "" });
      }
      return { ...msg, segments };
    }
    case "tool_start":
      segments.push({
        type: "tool",
        call_id: p.call_id || "",
        tool: p.tool || "",
        label: p.label || "",
        args_summary: p.args_summary,
      });
      return { ...msg, segments };
    case "tool_end": {
      const idx = segments.findIndex((s) => s.type === "tool" && s.call_id === p.call_id);
      if (idx >= 0) {
        segments[idx] = {
          ...(segments[idx] as ChatSegment & { type: "tool" }),
          status: p.status === "ok" ? "ok" : "error",
          summary: p.summary,
          detail: p.detail,
        };
      }
      return { ...msg, segments };
    }
    case "error":
      return { ...msg, error: p.message };
    default:
      return msg;
  }
}

interface Props {
  onSwitchMode: (m: ChatMode) => void;
}

export default function GrillWorkbench({ onSwitchMode }: Props) {
  const { t } = useI18n();
  const [sessionId, setSessionId] = useState("");
  const [ready, setReady] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [profile, setProfile] = useState<ProfileCard | null>(null);
  const [outline, setOutline] = useState<OutlineNode[]>([]);
  const [deliverables, setDeliverables] = useState<Deliverables | null>(null);
  const [showDeliverables, setShowDeliverables] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [regenError, setRegenError] = useState("");
  const [sessions, setSessions] = useState<GrillSessionSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const convRef = useRef<HTMLDivElement>(null);
  const activeIdRef = useRef("");
  const pollRef = useRef<number | null>(null);
  const sessionIdRef = useRef("");
  const stopFollow = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const loadSessions = useCallback(async (): Promise<GrillSessionSummary[]> => {
    try {
      const data = await api.grill.listSessions();
      const list = data.sessions || [];
      setSessions(list);
      return list;
    } catch {
      setSessions([]);
      return [];
    }
  }, []);

  /** 轮询跟随：Agent 在跑（running=true）时每 2s 拉状态，直到新 assistant 消息落库或进程结束 */
  const startFollow = useCallback(() => {
    stopFollow();
    pollRef.current = window.setInterval(async () => {
      let st: GrillSessionState | null = null;
      try {
        st = await api.grill.getState(sessionIdRef.current);
      } catch {
        return;
      }
      if (!st) return;
      setProfile(st.profile);
      setOutline(st.outline || []);
      if (st.deliverables) setDeliverables(st.deliverables);
      const stored = (st.messages || []) as StoredMessage[];
      setMessages(stored.map((m, i) => ({
        id: `hist-${i}`,
        role: m.role,
        segments: storedToSegments(m),
        error: m.error,
      })));
      if (st.running) return;
      stopFollow();
      setBusy(false);
      loadSessions();
    }, 2000);
  }, [stopFollow, loadSessions]);

  /** 打开指定会话：拉取状态并填充各面板；Agent 还在跑则挂占位消息并轮询跟随 */
  const openSession = useCallback(
    async (sid: string, st?: GrillSessionState | null) => {
      stopFollow();
      setBusy(false);
      setShowDeliverables(false);
      localStorage.setItem("grill.session-id", sid);
      sessionIdRef.current = sid;
      setSessionId(sid);
      const state = st ?? (await api.grill.getState(sid).catch(() => null));
      setProfile(state?.profile ?? null);
      setOutline(state?.outline || []);
      setDeliverables(state?.deliverables || null);
      const msgs = ((state?.messages || []) as StoredMessage[]).map((m, i) => ({
        id: `hist-${i}`,
        role: m.role,
        segments: storedToSegments(m),
        error: m.error,
      }));
      if (state?.running) {
        if (msgs[msgs.length - 1]?.role !== "assistant") {
          msgs.push({ id: `streaming-${Date.now()}`, role: "assistant", segments: [], error: undefined });
        }
        setMessages(msgs);
        setBusy(true);
        startFollow();
      } else {
        setMessages(msgs);
      }
      setReady(true);
    },
    [stopFollow, startFollow]
  );

  /** 新建空白态：不向后端建会话，首发消息时才创建（对齐人才问答的懒创建） */
  const resetToEmpty = useCallback(() => {
    stopFollow();
    setBusy(false);
    setShowDeliverables(false);
    sessionIdRef.current = "";
    setSessionId("");
    setMessages([]);
    setProfile(null);
    setOutline([]);
    setDeliverables(null);
    localStorage.removeItem("grill.session-id");
    setReady(true);
  }, [stopFollow]);

  // 挂载：恢复上次会话，没有则进入空白态（懒创建，不发空会话）
  useEffect(() => {
    (async () => {
      loadSessions();
      const cached = localStorage.getItem("grill.session-id");
      if (cached) {
        const cachedState = await api.grill.getState(cached).catch(() => null);
        if (cachedState) {
          await openSession(cached, cachedState);
          return;
        }
      }
      resetToEmpty();
    })();
    return stopFollow;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    convRef.current?.scrollTo(0, convRef.current.scrollHeight);
  }, [messages]);

  const updateActive = (e: SseEvent) => {
    const id = activeIdRef.current;
    setMessages((prev) => prev.map((m) => (m.id === id ? applyEvent(m, e) : m)));
  };

  const send = async (text: string) => {
    if (busy) return;
    // 懒创建：空白态首发时才向后端建会话（避免空会话污染侧栏）
    let sid = sessionId;
    if (!sid) {
      try {
        sid = (await api.grill.createSession()).session_id;
      } catch {
        return;
      }
      sessionIdRef.current = sid;
      setSessionId(sid);
      localStorage.setItem("grill.session-id", sid);
    }
    setBusy(true);
    const tempId = `streaming-${Date.now()}`;
    activeIdRef.current = tempId;
    setMessages((prev) => [
      ...prev,
      { id: `user-${Date.now()}`, role: "user", segments: [{ type: "text", text }] },
      { id: tempId, role: "assistant", segments: [] },
    ]);
    try {
      const resp = await api.grill.chatSSE(sid, text);
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error((err as { detail?: string }).detail || `HTTP ${resp.status}`);
      }
      for await (const raw of parseSSE(resp)) {
        const e = raw as unknown as SseEvent;
        if (e.type === "profile_update") {
          setProfile(e.payload.profile as ProfileCard);
        } else if (e.type === "outline_update") {
          setOutline(e.payload.outline as OutlineNode[]);
        } else if (e.type === "deliverables") {
          setDeliverables(e.payload as unknown as Deliverables);
        } else {
          updateActive(e);
        }
      }
    } catch (err) {
      updateActive({
        type: "error",
        payload: { message: err instanceof Error ? err.message : t("请求失败") },
      });
      startFollow();
      return;
    }
    setBusy(false);
    loadSessions();
  };

  const selectSession = (sid: string) => {
    if (busy || sid === sessionId) return;
    openSession(sid);
  };

  const newChat = () => {
    if (busy) return;
    resetToEmpty();
  };

  const handleDelete = async (ids: string[]) => {
    if (busy) return;
    await api.grill.deleteSessions(ids).catch(() => {});
    const list = await loadSessions();
    if (!ids.includes(sessionIdRef.current)) return;
    if (list.length) {
      await openSession(list[0].session_id);
    } else {
      resetToEmpty();
    }
  };

  const handleRegen = async () => {
    if (regenerating || !deliverables) return;
    setRegenerating(true);
    setRegenError("");
    try {
      setDeliverables(await api.grill.regenerateDeliverables(sessionId));
      setShowDeliverables(true);
    } catch (err) {
      setRegenError(err instanceof Error ? err.message : t("生成失败"));
      window.setTimeout(() => setRegenError(""), 5000);
    } finally {
      setRegenerating(false);
    }
  };

  return (
    <div>
      <PageToolbar
        title={t("画像澄清")}
        subtitle={t("面向用人部门 leader · 把模糊画像逼问清楚")}
        right={
          <div className="flex items-center gap-2">
            {regenError && <span className="text-label text-error">{regenError}</span>}
            <Button
              variant="tonal"
              icon="refresh"
              disabled={!deliverables || regenerating}
              title={deliverables ? t("基于当前画像与对话重新生成") : t("需求包生成后可重新生成")}
              onClick={handleRegen}
            >
              {regenerating ? t("生成中…") : t("重新生成需求包")}
            </Button>
            <SegmentedButtons
              value="clarify"
              onChange={(m) => onSwitchMode(m)}
              options={[
                { value: "qa", label: t("人才问答"), icon: "forum" },
                { value: "clarify", label: t("画像澄清"), icon: "psychology_alt" },
              ]}
            />
          </div>
        }
      />

      <div className="app-workspace-frame flex gap-4 2xl:gap-6 min-h-0">
        {/* 侧栏：历史会话 */}
        <SessionSidebar
          sessions={sessions}
          currentId={sessionId}
          busy={busy}
          onSelect={selectSession}
          onCreate={newChat}
          onDelete={handleDelete}
        />

        {/* 左栏：对话流 */}
        <div data-tour="chat-flow" className="flex-1 min-w-[360px] flex flex-col">
          <div ref={convRef} className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-5 pr-1 pb-2">
            {!ready ? (
              <div className="flex-1 flex items-center justify-center">
                <LoadingIndicator size={28} label={t("初始化会话…")} />
              </div>
            ) : messages.length === 0 ? (
              <div className="flex-1 flex flex-col items-center justify-center text-center gap-3">
                <Icon name="psychology" size={40} className="text-on-surface-variant" />
                <p className="text-title">{t("说说你想招什么样的人？")}</p>
                <p className="text-body-sm text-on-surface-variant">
                  {t("Agent 会像资深 HR 一样追问，右侧大纲与画像卡实时填充")}
                </p>
                <div className="flex flex-wrap justify-center gap-2">
                  {["我们想招个后端开发工程师。", "招一个 AI 产品经理实习生，base 北京。"].map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => send(t(s))}
                      className="state-layer rounded-full border border-primary/50 bg-surface-lowest px-3 py-1.5 text-body-sm text-primary cursor-pointer hover:bg-primary-container"
                    >
                      {t(s)}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((msg, idx) => {
                if (msg.role === "user") {
                  return (
                    <div
                      key={msg.id}
                      className="chat-enter self-end max-w-[80%] px-4 py-3 rounded-lg bg-primary-container text-on-primary-container text-body whitespace-pre-wrap"
                    >
                      {msg.segments.map((s) => (s.type === "text" ? s.text : "")).join("")}
                    </div>
                  );
                }
                // 该 assistant 消息之后的下一条用户消息：历史回放时供卡片反推已选项
                const nextUser = messages.slice(idx + 1).find((m) => m.role === "user");
                const userReply = nextUser?.segments
                  .map((s) => (s.type === "text" ? s.text : ""))
                  .join("");
                return (
                  <AssistantMessage
                    key={msg.id}
                    message={msg}
                    busy={busy && msg.id === activeIdRef.current}
                    interactive={idx === messages.length - 1 && !busy}
                    onSend={send}
                    userReply={userReply}
                  />
                );
              })
            )}
          </div>
          <ChatInput busy={busy} onSend={send} />
        </div>

        {/* 中栏：提问大纲 */}
        <div data-tour="outline" className="w-[240px] 2xl:w-[300px] shrink-0 min-h-0">
          <OutlinePanel outline={outline} />
        </div>

        {/* 右栏：画像卡 */}
        <div data-tour="profile" className="w-[300px] 2xl:w-[360px] shrink-0 min-h-0">
          <ProfileCardPanel
            profile={profile}
            hasDeliverables={!!deliverables}
            busy={busy}
            onConfirm={() => send(t("画像总结确认无误，请生成需求包。"))}
            onOpenDeliverables={() => setShowDeliverables(true)}
          />
        </div>
      </div>

      {showDeliverables && deliverables && (
        <DeliverablesPanel deliverables={deliverables} onClose={() => setShowDeliverables(false)} />
      )}
    </div>
  );
}
