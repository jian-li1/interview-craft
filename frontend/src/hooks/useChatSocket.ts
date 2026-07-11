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
  const askQuestion = useChatStore((s) => s.askQuestion);
  const setAgentRunning = useChatStore((s) => s.setAgentRunning);
  const finishRunTiming = useChatStore((s) => s.finishRunTiming);
  const startCompaction = useChatStore((s) => s.startCompaction);
  const finishCompaction = useChatStore((s) => s.finishCompaction);
  const setContextUsage = useChatStore((s) => s.setContextUsage);
  const refetchCurriculum = useCurriculumStore((s) => s.refetch);

  useEffect(() => {
    if (!conversationId) return;

    const socket = new ChatSocket(conversationId);
    socketRef.current = socket;

    // Per-message buffers of not-yet-applied streaming deltas, flushed at most
    // once per animation frame so a fast token stream produces one store update
    // per frame instead of one per token (which caused nested sync re-renders
    // and React's "Maximum update depth exceeded").
    const textBuf = new Map<string, string>();
    const reasoningBuf = new Map<string, string>();
    let rafId: number | null = null;

    // Applies all buffered deltas in one store update apiece, then clears the buffers.
    const flushDeltas = () => {
      if (rafId !== null) {
        cancelAnimationFrame(rafId);
        rafId = null;
      }
      textBuf.forEach((delta, id) => appendTextDelta(id, delta));
      textBuf.clear();
      reasoningBuf.forEach((delta, id) => appendReasoningDelta(id, delta));
      reasoningBuf.clear();
    };

    // Schedules a single flush on the next animation frame (idempotent — a
    // pending rAF is reused rather than stacking more).
    const scheduleFlush = () => {
      if (rafId === null) rafId = requestAnimationFrame(flushDeltas);
    };

    const offEvent = socket.onEvent((event: ServerEvent) => {
      // Any non-delta event must see already-buffered deltas applied first,
      // so ordering is preserved (e.g. message_end shouldn't clear the
      // streaming flag before its own buffered text has landed).
      if (event.type !== "text_delta" && event.type !== "reasoning_delta") {
        flushDeltas();
      }
      switch (event.type) {
        case "session_ready":
          setCurriculumId(event.curriculum_id);
          // Show Stop button immediately on reconnect if a turn is still in flight.
          setAgentRunning(event.agent_running);
          break;
        case "message_start":
          startMessage(event.message_id);
          break;
        case "reasoning_delta":
          // Accumulate into the buffer rather than dispatching immediately;
          // scheduleFlush coalesces this with any deltas arriving this frame.
          reasoningBuf.set(event.message_id, (reasoningBuf.get(event.message_id) ?? "") + event.delta);
          scheduleFlush();
          break;
        case "text_delta":
          textBuf.set(event.message_id, (textBuf.get(event.message_id) ?? "") + event.delta);
          scheduleFlush();
          break;
        case "tool_call_start":
          startToolCall(event.message_id, event.tool_call_id, event.name, event.input);
          break;
        case "tool_call_result":
          resolveToolCall(
            event.message_id,
            event.tool_call_id,
            event.output_full,
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
        case "user_input_requested":
          // Renders the QuestionCard inline (mirrors plan_proposed -> proposePlan).
          askQuestion(event.question, event.options);
          break;
        case "curriculum_updated":
          void refetchCurriculum({
            scope: event.scope,
            moduleId: event.module_id,
            sectionId: event.section_id,
          });
          break;
        case "compaction_start":
          // Renders the "Auto-compacting…" spinner chip immediately, ahead of the
          // (potentially slow) small-model summarization call finishing.
          startCompaction();
          break;
        case "compaction":
          // Resolves the running chip in place (or, on reconnect replay, appends an
          // already-done chip) — no more toast, the transcript chip is the UI now.
          finishCompaction(
            event.summary,
            event.tokens_before,
            event.tokens_after,
            event.compacted_through
          );
          break;
        case "context_usage":
          setContextUsage(event.tokens, event.limit, event.threshold);
          break;
        case "agent_done":
          // Freeze the SERVER-measured elapsed onto the run's tail message (authoritative,
          // overwrites any local approximation) before clearing agentRunning.
          finishRunTiming(event.elapsed_ms);
          setAgentRunning(false);
          break;
        case "error":
          toast.error(event.message);
          if (!event.recoverable) {
            // Run is over; stamp whatever elapsed onto the tail message.
            finishRunTiming();
            setAgentRunning(false);
          }
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
      // Apply any still-buffered deltas (and cancel a pending rAF) before
      // tearing down, so nothing streamed is lost on unmount.
      flushDeltas();
      offEvent();
      offState();
      socket.close();
      socketRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  return socketRef;
}
