"use client";

import { use, useEffect, useRef, useState } from "react";
import { MessageCircle, Workflow } from "lucide-react";
import { toast } from "sonner";
import { ChatPanel } from "@/components/studio/chat/ChatPanel";
import { CurriculumPanel } from "@/components/studio/curriculum/CurriculumPanel";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/Tabs";
import { useChatSocket } from "@/hooks/useChatSocket";
import { useIsMobile } from "@/hooks/useIsMobile";
import { useChatStore } from "@/stores/useChatStore";
import { useCurriculumStore } from "@/stores/useCurriculumStore";
import { conversationsApi, ApiError } from "@/lib/api";

interface StudioPageProps {
  params: Promise<{ conversationId: string }>;
}

export default function StudioPage({ params }: StudioPageProps) {
  const { conversationId } = use(params);

  const setConversationId = useChatStore((s) => s.setConversationId);
  const curriculumId = useChatStore((s) => s.curriculumId);
  const hydrateHistory = useChatStore((s) => s.hydrateHistory);
  const resetChat = useChatStore((s) => s.reset);
  const resetCurriculum = useCurriculumStore((s) => s.reset);
  const messages = useChatStore((s) => s.messages);
  const connectionState = useChatStore((s) => s.connectionState);
  const addUserMessage = useChatStore((s) => s.addUserMessage);
  const setAgentRunning = useChatStore((s) => s.setAgentRunning);

  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [prefillText, setPrefillText] = useState<string | undefined>(undefined);
  const [mobileTab, setMobileTab] = useState<"chat" | "curriculum">("chat");

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
    if (messages.length > 0) return;

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
    messages.length,
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

  function handleExplain(prompt: string) {
    setPrefillText(prompt);
    setMobileTab("chat");
  }

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
      <div className="flex h-[calc(100vh-3.5rem)] min-h-0 flex-col">
        <Tabs
          value={mobileTab}
          onValueChange={(v) => setMobileTab(v as "chat" | "curriculum")}
          className="flex min-h-0 flex-1 flex-col"
        >
          <div className="flex shrink-0 justify-center border-b border-border p-2">
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
    <div className="flex h-[calc(100vh-3.5rem)] min-h-0">
      <div className="h-full min-h-0 w-[40%] min-w-[380px] max-w-[560px] shrink-0 border-r border-border">
        {chatPanel}
      </div>
      <div className="h-full min-h-0 flex-1">{curriculumPanel}</div>
    </div>
  );
}
