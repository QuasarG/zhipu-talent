import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, parseSSE } from "@/lib/api";
import type { ChatConversation, ChatEvent, ChatMessage, ChatSegment } from "@/lib/types";
import PageToolbar from "@/components/layout/PageToolbar";
import Icon from "@/components/ui/Icon";
import LoadingIndicator from "@/components/ui/LoadingIndicator";
import ChatSidebar from "@/features/chat/ChatSidebar";
import ChatInput from "@/features/chat/ChatInput";
import AssistantMessage from "@/features/chat/AssistantMessage";
import { useSessionState } from "@/lib/sessionState";
import { useI18n } from "@/lib/i18n";
import SegmentedButtons from "@/components/ui/SegmentedButtons";
import GrillWorkbench, { type ChatMode } from "@/features/grill/GrillWorkbench";

type LocalMessage = ChatMessage & { error?: string };

/** 逐事件更新正在流式生成的 assistant 消息 */
function applyEvent(msg: LocalMessage, e: ChatEvent): LocalMessage {
  const segments = [...msg.content.segments];
  switch (e.type) {
    case "meta":
      return { ...msg, id: e.payload.message_id };
    case "answer_delta": {
      const last = segments[segments.length - 1];
      if (last?.type === "text") {
        segments[segments.length - 1] = { ...last, text: last.text + e.payload.text };
      } else {
        segments.push({ type: "text", text: e.payload.text });
      }
      return { ...msg, content: { segments } };
    }
    case "tool_start":
      segments.push({
        type: "tool",
        call_id: e.payload.call_id,
        tool: e.payload.tool,
        label: e.payload.label,
        args_summary: e.payload.args_summary,
      });
      return { ...msg, content: { segments } };
    case "tool_end": {
      const idx = segments.findIndex((s) => s.type === "tool" && s.call_id === e.payload.call_id);
      if (idx >= 0) {
        segments[idx] = {
          ...(segments[idx] as ChatSegment & { type: "tool" }),
          status: e.payload.status,
          summary: e.payload.summary,
          detail: e.payload.detail,
        };
      }
      return { ...msg, content: { segments } };
    }
    case "action_required":
      segments.push({
        type: "action",
        action_id: e.payload.action_id,
        kind: e.payload.kind,
        payload: e.payload.payload,
        decision: null,
      });
      return { ...msg, content: { segments }, status: "awaiting_action" };
    case "sources":
      return { ...msg, citations: e.payload.items };
    case "error":
      return { ...msg, error: e.payload.message };
    case "done":
      return { ...msg, status: e.payload.status };
    default:
      return msg;
  }
}

export default function TalentChat() {
  const [mode, setMode] = useSessionState<ChatMode>("talent-chat.mode", "qa");
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [currentId, setCurrentId] = useSessionState<string | null>("talent-chat.conversation-id", null);
  const [messages, setMessages] = useState<LocalMessage[]>([]);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [busy, setBusy] = useState(false);
  const convRef = useRef<HTMLDivElement>(null);
  const activeIdRef = useRef<string>("");
  // 发送时新建会话会触发 currentId 变化，跳过一次消息加载（否则会清掉刚追加的消息）
  const skipNextLoad = useRef(false);
  // 状态跟随：running 消息的轮询句柄 + currentId 镜像（轮询回调里读不到最新 state）
  const pollRef = useRef<number | null>(null);
  const currentIdRef = useRef<string | null>(null);
  const { t, lang } = useI18n();
  // 档案页「问问 AI」跳转：?ask= 预填输入框（读一次即清，避免刷新重复触发）
  const [searchParams, setSearchParams] = useSearchParams();
  const prefill = searchParams.get("ask") || "";
  useEffect(() => {
    if (prefill) setSearchParams({}, { replace: true });
  }, [prefill, setSearchParams]);

  const stopFollow = useCallback(() => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const loadConversations = useCallback(async () => {
    try {
      setConversations(await api.chat.listConversations());
    } catch (err) {
      console.error(err);
    }
  }, []);

  /** 状态跟随：后端还在跑（status=running）时每 2s 拉一次消息，直到完成 */
  const startFollow = useCallback(
    (convId: string, messageId?: string) => {
      stopFollow();
      if (messageId) activeIdRef.current = messageId;
      setBusy(true);
      pollRef.current = window.setInterval(async () => {
        try {
          const msgs = await api.chat.getMessages(convId);
          if (currentIdRef.current !== convId) {
            stopFollow();
            setBusy(false);
            return;
          }
          setMessages(msgs);
          const lastA = [...msgs].reverse().find((m) => m.role === "assistant");
          if (!lastA || lastA.status !== "running") {
            stopFollow();
            setBusy(false);
            loadConversations();
          }
        } catch {
          // 网络抖动：下一轮再试
        }
      }, 2000);
    },
    [loadConversations, stopFollow]
  );

  const loadMessages = useCallback(
    async (id: string) => {
      setLoadingMsgs(true);
      try {
        const msgs = await api.chat.getMessages(id);
        setMessages(msgs);
        // 刷新/切页回来发现还在跑：进入轮询跟随
        const lastA = [...msgs].reverse().find((m) => m.role === "assistant");
        if (lastA && lastA.status === "running") {
          startFollow(id, lastA.id);
        } else {
          stopFollow();
          setBusy(false);
        }
      } catch {
        // 会话可能已被删除：清掉记住的 id
        setMessages([]);
        setCurrentId(null);
      } finally {
        setLoadingMsgs(false);
      }
    },
    [setCurrentId, startFollow, stopFollow]
  );

  useEffect(() => {
    loadConversations();
    return stopFollow;
  }, [loadConversations, stopFollow]);

  useEffect(() => {
    currentIdRef.current = currentId;
    if (!currentId) {
      setMessages([]);
      return;
    }
    if (skipNextLoad.current) {
      skipNextLoad.current = false;
      return;
    }
    loadMessages(currentId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId]);

  useEffect(() => {
    convRef.current?.scrollTo(0, convRef.current.scrollHeight);
  }, [messages]);

  // 画像澄清模式：渲染独立工作台，两套会话/Agent 完全隔离
  if (mode === "clarify") {
    return <GrillWorkbench onSwitchMode={setMode} />;
  }

  const updateActive = (e: ChatEvent) => {
    const id = activeIdRef.current;
    setMessages((prev) => {
      const next = prev.map((m) => (m.id === id ? applyEvent(m, e) : m));
      // meta 事件换了真实 message_id，ref 跟着换
      if (e.type === "meta") activeIdRef.current = e.payload.message_id;
      return next;
    });
  };

  /** 消费一条 SSE 流（ask / action 共用） */
  const consume = async (resp: Response) => {
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    for await (const event of parseSSE(resp)) {
      updateActive(event as unknown as ChatEvent);
    }
  };

  const send = async (text: string) => {
    if (busy) return;
    setBusy(true);
    let convId = currentId;
    try {
      if (!convId) {
        const conv = await api.chat.createConversation();
        convId = conv.id;
        skipNextLoad.current = true;
        setCurrentId(conv.id);
      }
      const tempId = `streaming-${Date.now()}`;
      activeIdRef.current = tempId;
      const userMsg: LocalMessage = {
        id: `user-${Date.now()}`,
        conversation_id: convId,
        role: "user",
        content: { segments: [{ type: "text", text }] },
        citations: [],
        status: "completed",
        created_at: new Date().toISOString(),
      };
      const assistantMsg: LocalMessage = {
        id: tempId,
        conversation_id: convId,
        role: "assistant",
        content: { segments: [] },
        citations: [],
        status: "completed",
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      await consume(await api.chat.askSSE(convId, text, lang));
    } catch (err) {
      updateActive({ type: "error", payload: { message: err instanceof Error ? err.message : t("请求失败") } });
      // SSE 中断兜底：后端可能还在跑，转轮询跟随
      if (convId) startFollow(convId);
    } finally {
      if (pollRef.current === null) setBusy(false);
      loadConversations();
    }
  };

  const decide = async (actionId: string, decision: Record<string, unknown>) => {
    if (!currentId || busy) return;
    setBusy(true);
    // 本地先定格卡片，再让后端续跑
    setMessages((prev) =>
      prev.map((m) => ({
        ...m,
        content: {
          segments: m.content.segments.map((s) =>
            s.type === "action" && s.action_id === actionId ? { ...s, decision } : s
          ),
        },
        status: m.content.segments.some((s) => s.type === "action" && s.action_id === actionId)
          ? "completed"
          : m.status,
      }))
    );
    try {
      await consume(await api.chat.actionSSE(currentId, actionId, decision, lang));
    } catch (err) {
      updateActive({ type: "error", payload: { message: err instanceof Error ? err.message : t("请求失败") } });
      // SSE 中断兜底：后端可能还在跑，转轮询跟随
      startFollow(currentId);
    } finally {
      if (pollRef.current === null) setBusy(false);
      loadConversations();
    }
  };

  const handleCreate = () => {
    if (busy) return;
    setCurrentId(null);
    setMessages([]);
  };

  const handleRename = async (id: string, title: string) => {
    try {
      const conv = await api.chat.renameConversation(id, title);
      setConversations((prev) => prev.map((c) => (c.id === id ? conv : c)));
    } catch (err) {
      console.error(err);
    }
  };

  const handleDelete = async (id: string) => {
    if (busy) return;
    try {
      await api.chat.deleteConversation(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (currentId === id) {
        setCurrentId(null);
        setMessages([]);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant");
  const awaitingAction = lastAssistant?.status === "awaiting_action";

  return (
    <div className="flex flex-col h-[calc(100vh-24px)]">
      <PageToolbar
        title={t("人才问答")}
        subtitle={t("库内优先 · 必要时联网调查")}
        right={
          <SegmentedButtons
            value={mode}
            onChange={setMode}
            options={[
              { value: "qa", label: t("人才问答"), icon: "forum" },
              { value: "clarify", label: t("画像澄清"), icon: "psychology_alt" },
            ]}
          />
        }
      />

      <div className="flex gap-6 flex-1 min-h-0">
        <ChatSidebar
          conversations={conversations}
          currentId={currentId}
          onSelect={(id) => !busy && setCurrentId(id)}
          onCreate={handleCreate}
          onRename={handleRename}
          onDelete={handleDelete}
        />

        <div className="flex-1 min-w-0 flex flex-col w-full max-w-5xl mx-auto">
          <div ref={convRef} className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-5 pr-1 pb-2">
            {loadingMsgs ? (
              <div className="flex-1 flex items-center justify-center">
                <LoadingIndicator size={28} label={t("加载会话…")} />
              </div>
            ) : messages.length === 0 ? (
              <div className="flex-1 flex flex-col items-center justify-center text-center gap-3">
                <Icon name="psychology" size={40} className="text-on-surface-variant" />
                <p className="text-title">{t("询问人才、比较经历，或调查一个明确人物")}</p>
                <p className="text-body-sm text-on-surface-variant">
                  {t("Agent 会自主调用库内检索与外部工具；遇到歧义会请你决策")}
                </p>
              </div>
            ) : (
              messages.map((msg) =>
                msg.role === "user" ? (
                  <div
                    key={msg.id}
                    className="chat-enter self-end max-w-[80%] px-4 py-3 rounded-lg bg-primary-container text-on-primary-container text-body whitespace-pre-wrap"
                  >
                    {msg.content.segments.map((s) => (s.type === "text" ? s.text : "")).join("")}
                  </div>
                ) : (
                  <AssistantMessage
                    key={msg.id}
                    message={msg}
                    error={msg.error}
                    busy={busy && msg.id === activeIdRef.current}
                    onDecide={decide}
                  />
                )
              )
            )}
          </div>

          <ChatInput busy={busy} awaitingAction={awaitingAction} onSend={send} initialValue={prefill} />
        </div>
      </div>
    </div>
  );
}
