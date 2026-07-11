"use client";

import { use, useCallback, useEffect, useRef, useState } from "react";
import { MessageCircle, Workflow } from "lucide-react";
import { toast } from "sonner";
import { ChatPanel } from "@/components/studio/chat/ChatPanel";
import { CurriculumPanel } from "@/components/studio/curriculum/CurriculumPanel";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/Tabs";
import { useChatSocket } from "@/hooks/useChatSocket";
import { useIsMobile } from "@/hooks/useIsMobile";
import { usePanelResize } from "@/hooks/usePanelResize";
import { useChatStore } from "@/stores/useChatStore";
import { useCurriculumStore } from "@/stores/useCurriculumStore";
import { conversationsApi, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

interface StudioPageProps {
  // Next.js 15 App Router passes dynamic route params as a Promise (to
  // support async param resolution); unwrapped below via React's `use()`.
  params: Promise<{ conversationId: string }>;
}

/**
 * `/studio/[conversationId]` — the core studio page: a split-panel layout
 * pairing the live agent chat (`ChatPanel`) with the curriculum being built
 * (`CurriculumPanel`), for one conversation at a time.
 *
 * `conversationId` flow: the dynamic route param arrives as a Promise (App
 * Router convention) and is unwrapped with `use(params)`. It's then threaded
 * into `useChatSocket(conversationId)` to open/own the WebSocket connection
 * for this conversation, into `useChatStore.setConversationId` so the chat
 * store scopes its state to this conversation, and into
 * `conversationsApi.messages(conversationId)` to fetch prior history.
 *
 * Layout split: on desktop, a drag-resizable chat column (default 480px,
 * clamped to [340, min(720, 60vw)], persisted to `localStorage` under
 * `ic:studio-chat-width`) on the left, a pointer/keyboard-operable divider,
 * and a flexible curriculum column filling the rest; on mobile
 * (`useIsMobile`), the two panels become tabs ("Chat" / "Curriculum") in a
 * single-column layout instead of a side-by-side split. Only one layout is
 * mounted at a time (not both, toggled via CSS) so that expensive
 * client-only views inside `CurriculumPanel` (React Flow canvas, Mermaid
 * diagrams) never mount twice simultaneously.
 *
 * Resume/reconnect logic on mount:
 * - The history-hydration effect resets both the chat and curriculum stores
 *   and re-fetches message history via `conversationsApi.messages` whenever
 *   `conversationId` changes (including first mount), so navigating between
 *   studio conversations doesn't leak state from the previous one.
 * - The "pending prompt" effect handles the case where this conversation was
 *   just created from the dashboard's prompt box: the conversation's opening
 *   message is stashed in `sessionStorage` (key `ic:pending-prompt:{id}`)
 *   before navigation, because creating the conversation only provisions
 *   Firestore docs — the agent turn doesn't start until the first
 *   `user_message` WS frame is actually sent. Once history has loaded (so we
 *   know there's no existing history already covering it), the socket is
 *   open, and no messages exist yet, that pending prompt is sent exactly
 *   once (guarded by the `initialPromptSent` ref) and removed from
 *   `sessionStorage`.
 * - `useChatSocket` itself (see `hooks/useChatSocket.ts`) owns automatic
 *   reconnect/backoff for the underlying WebSocket; this page only reacts to
 *   the resulting connection state to decide when it's safe to send the
 *   pending prompt.
 */
export default function StudioPage({ params }: StudioPageProps) {
  const { conversationId } = use(params);

  const setConversationId = useChatStore((s) => s.setConversationId);
  const curriculumId = useChatStore((s) => s.curriculumId);
  const hydrateHistory = useChatStore((s) => s.hydrateHistory);
  const resetChat = useChatStore((s) => s.reset);
  const resetCurriculum = useCurriculumStore((s) => s.reset);
  // Focus mode (set from CurriculumPanel's full-screen toggle): hides the chat
  // column and lets the curriculum panel claim the full viewport height.
  const focusMode = useCurriculumStore((s) => s.focusMode);
  // Boolean selector (not the raw array) so this page doesn't re-render on
  // every streaming text delta — the messages array identity changes per
  // delta, but this boolean only flips once (empty -> non-empty).
  const hasMessages = useChatStore((s) => s.messages.length > 0);
  const connectionState = useChatStore((s) => s.connectionState);
  const addUserMessage = useChatStore((s) => s.addUserMessage);
  const setAgentRunning = useChatStore((s) => s.setAgentRunning);

  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [prefillText, setPrefillText] = useState<string | undefined>(undefined);
  const [mobileTab, setMobileTab] = useState<"chat" | "curriculum">("chat");

  // Desktop chat-column resize: drag/keyboard behavior extracted into a shared
  // hook (also used by ReaderView's TOC sidebar) — see usePanelResize.ts.
  const { width: chatWidth, isDragging, separatorProps: chatSeparatorProps } = usePanelResize({
    storageKey: "ic:studio-chat-width",
    defaultWidth: 480,
    minWidth: 340,
    maxWidth: 720,
    maxViewportRatio: 0.6,
  });

  const socketRef = useChatSocket(conversationId);
  const initialPromptSent = useRef(false);

  // If this conversation was just created from the dashboard's prompt box,
  // its opening message hasn't been sent to the agent yet (creating the
  // conversation only provisions the Firestore docs — the agent turn only
  // starts on the first `user_message` WS frame). Auto-send it now that the
  // socket is open and we've confirmed there's no existing history.
  useEffect(() => {
    if (initialPromptSent.current) return;
    if (historyLoading || connectionState !== "open") return;
    if (hasMessages) return;

    const key = `ic:pending-prompt:${conversationId}`;
    const pending = sessionStorage.getItem(key);
    if (!pending) return;

    initialPromptSent.current = true;
    sessionStorage.removeItem(key);
    addUserMessage(pending);
    setAgentRunning(true);
    socketRef.current?.sendUserMessage(pending);
  }, [
    conversationId,
    historyLoading,
    connectionState,
    hasMessages,
    addUserMessage,
    setAgentRunning,
    socketRef,
  ]);

  // Reset per-conversation state and hydrate message history on mount / when
  // the conversationId changes.
  useEffect(() => {
    resetChat();
    resetCurriculum();
    setConversationId(conversationId);
    setHistoryLoading(true);
    setHistoryError(null);
    initialPromptSent.current = false;

    let cancelled = false;
    (async () => {
      try {
        const messages = await conversationsApi.messages(conversationId);
        if (!cancelled) hydrateHistory(messages);
      } catch (err) {
        if (!cancelled) {
          const message =
            err instanceof ApiError ? err.message : "Couldn't load this conversation";
          setHistoryError(message);
          toast.error(message);
        }
      } finally {
        if (!cancelled) setHistoryLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  // useCallback (no deps: only calls stable setters) so this stays a stable
  // reference passed down to CurriculumPanel, letting its memo() actually work.
  const handleExplain = useCallback((prompt: string) => {
    setPrefillText(prompt);
    setMobileTab("chat");
  }, []);

  const isMobile = useIsMobile();

  const chatPanel = (
    <ChatPanel
      conversationId={conversationId}
      socketRef={socketRef}
      historyLoading={historyLoading}
      historyError={historyError}
      prefillText={prefillText}
      onPrefillConsumed={() => setPrefillText(undefined)}
    />
  );

  const curriculumPanel = (
    <CurriculumPanel curriculumId={curriculumId} onExplain={handleExplain} />
  );

  // Render only one layout at a time (rather than hiding the other with CSS)
  // so expensive client-only views (React Flow canvas, Mermaid) don't mount
  // twice at once.
  if (isMobile === null) {
    // Avoid a flash of the wrong layout before we know the viewport size.
    return <div className="h-[calc(100vh-3.5rem)]" />;
  }

  if (isMobile) {
    return (
      // Focus mode hides the app header, so the page claims the full viewport height instead.
      <div className={cn("flex min-h-0 flex-col", focusMode ? "h-screen" : "h-[calc(100vh-3.5rem)]")}>
        <Tabs
          value={mobileTab}
          onValueChange={(v) => setMobileTab(v as "chat" | "curriculum")}
          className="flex min-h-0 flex-1 flex-col"
        >
          {/* Tab switcher hidden in focus mode — the focus button only reaches curriculum, so it's already the visible tab. */}
          <div className={cn("flex shrink-0 justify-center border-b border-border p-2", focusMode && "hidden")}>
            <TabsList aria-label="Studio view">
              <TabsTrigger value="chat">
                <span className="flex items-center gap-1.5">
                  <MessageCircle className="h-3.5 w-3.5" aria-hidden="true" />
                  Chat
                </span>
              </TabsTrigger>
              <TabsTrigger value="curriculum">
                <span className="flex items-center gap-1.5">
                  <Workflow className="h-3.5 w-3.5" aria-hidden="true" />
                  Curriculum
                </span>
              </TabsTrigger>
            </TabsList>
          </div>
          <TabsContent value="chat" className="min-h-0 flex-1">
            {chatPanel}
          </TabsContent>
          <TabsContent value="curriculum" className="min-h-0 flex-1">
            {curriculumPanel}
          </TabsContent>
        </Tabs>
      </div>
    );
  }

  return (
    // Focus mode hides the app header, so the page claims the full viewport height instead.
    <div className={cn("flex min-h-0", focusMode ? "h-screen" : "h-[calc(100vh-3.5rem)]")}>
      {/* Chat column: width is drag-resizable via the divider; pointer-events
          disabled while dragging so a fast drag doesn't get swallowed by
          content underneath (e.g. iframes) or trigger text selection.
          CSS-hidden (not unmounted) in focus mode so composer draft/scroll survive toggling. */}
      <div
        style={{ width: chatWidth }}
        className={cn("h-full min-h-0 shrink-0", isDragging && "pointer-events-none", focusMode && "hidden")}
      >
        {chatPanel}
      </div>
      {/* Drag/keyboard-resizable divider between chat and curriculum columns;
          also serves as the visual border previously on the chat column.
          Hidden alongside the chat column in focus mode. */}
      <div
        {...chatSeparatorProps}
        aria-label="Resize chat panel"
        className={cn(
          "h-full w-1.5 shrink-0 cursor-col-resize touch-none bg-border transition-colors",
          "hover:bg-primary/50 focus-visible:bg-primary/50 focus-visible:outline-none",
          isDragging && "bg-primary/50",
          focusMode && "hidden"
        )}
      />
      {/* min-w-0 overrides flex default to prevent long-nowrap text from causing
          horizontal overflow. */}
      <div
        className={cn(
          "h-full min-h-0 min-w-0 flex-1",
          isDragging && "pointer-events-none"
        )}
      >
        {curriculumPanel}
      </div>
    </div>
  );
}
