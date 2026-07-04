"use client";

import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { ChatSocket, type ConnectionState } from "@/lib/ws";
import { useChatStore } from "@/stores/useChatStore";
import { useCurriculumStore } from "@/stores/useCurriculumStore";
import type { ServerEvent } from "@/lib/types";

/**
 * Owns the ChatSocket lifecycle for a conversation: connects on mount,
 * dispatches every server event into useChatStore / useCurriculumStore,
 * and closes cleanly on unmount. Reconnect + backoff is handled inside
 * ChatSocket itself; this hook only surfaces connection state as toasts.
 */
export function useChatSocket(conversationId: string | null) {
  const socketRef = useRef<ChatSocket | null>(null);
  const wasReconnecting = useRef(false);

  const setConnectionState = useChatStore((s) => s.setConnectionState);
  const setCurriculumId = useChatStore((s) => s.setCurriculumId);
  const startMessage = useChatStore((s) => s.startMessage);
  const appendReasoningDelta = useChatStore((s) => s.appendReasoningDelta);
  const appendTextDelta = useChatStore((s) => s.appendTextDelta);
  const endMessage = useChatStore((s) => s.endMessage);
  const startToolCall = useChatStore((s) => s.startToolCall);
  const resolveToolCall = useChatStore((s) => s.resolveToolCall);
  const setPhase = useChatStore((s) => s.setPhase);
  const setProgress = useChatStore((s) => s.setProgress);
  const proposePlan = useChatStore((s) => s.proposePlan);
  const setAgentRunning = useChatStore((s) => s.setAgentRunning);
  const refetchCurriculum = useCurriculumStore((s) => s.refetch);

  useEffect(() => {
    if (!conversationId) return;

    const socket = new ChatSocket(conversationId);
    socketRef.current = socket;

    const offEvent = socket.onEvent((event: ServerEvent) => {
      switch (event.type) {
        case "session_ready":
          setCurriculumId(event.curriculum_id);
          break;
        case "message_start":
          startMessage(event.message_id);
          break;
        case "reasoning_delta":
          appendReasoningDelta(event.message_id, event.delta);
          break;
        case "text_delta":
          appendTextDelta(event.message_id, event.delta);
          break;
        case "tool_call_start":
          startToolCall(event.message_id, event.tool_call_id, event.name, event.input);
          break;
        case "tool_call_result":
          resolveToolCall(
            event.message_id,
            event.tool_call_id,
            event.output_preview,
            event.status,
            event.elapsed_ms
          );
          break;
        case "message_end":
          endMessage(event.message_id);
          break;
        case "phase_change":
          setPhase(event.phase, event.label);
          break;
        case "progress":
          setProgress(event.completed, event.total, event.detail);
          break;
        case "plan_proposed":
          proposePlan(event.plan);
          break;
        case "curriculum_updated":
          void refetchCurriculum({
            scope: event.scope,
            moduleId: event.module_id,
            sectionId: event.section_id,
          });
          break;
        case "compaction":
          toast.info("Conversation history compacted to save context.");
          break;
        case "agent_done":
          setAgentRunning(false);
          break;
        case "error":
          toast.error(event.message);
          if (!event.recoverable) setAgentRunning(false);
          break;
        case "pong":
          break;
      }
    });

    const offState = socket.onStateChange((state: ConnectionState) => {
      setConnectionState(state);
      if (state === "reconnecting") {
        wasReconnecting.current = true;
        toast.loading("Reconnecting…", { id: "ws-reconnect" });
      } else if (state === "open") {
        if (wasReconnecting.current) {
          toast.success("Reconnected", { id: "ws-reconnect" });
          wasReconnecting.current = false;
        } else {
          toast.dismiss("ws-reconnect");
        }
      }
    });

    socket.connect();

    return () => {
      offEvent();
      offState();
      socket.close();
      socketRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  return socketRef;
}
