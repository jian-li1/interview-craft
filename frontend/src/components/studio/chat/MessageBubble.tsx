"use client";

import { memo, useEffect, useState } from "react";
import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { User, Sparkles, Clock } from "lucide-react";
import { ReasoningBlock } from "@/components/studio/chat/ReasoningBlock";
import { ToolCallGroup } from "@/components/studio/chat/ToolCallCard";
import { cn, formatRunDuration } from "@/lib/utils";
import { useChatStore } from "@/stores/useChatStore";
import type { ChatMessage } from "@/stores/useChatStore";

/**
 * Renders a single chat message (user or assistant) with role-based styling:
 * user messages are right-aligned with a filled primary-color bubble and a
 * "flipped" tail (`rounded-tr-sm`); assistant messages are left-aligned with
 * a card-colored bubble (`rounded-tl-sm`) and render Markdown (GFM + syntax
 * highlighting) instead of plain text.
 *
 * Assistant-only sub-blocks, in display order:
 *  - `ReasoningBlock` — the agent's native reasoning/thinking stream for this
 *    message, populated by `reasoning_delta` WS events.
 *  - `ToolCallGroup` — any tool calls the assistant made while composing
 *    this message.
 *  - the text bubble itself, populated by `text_delta` WS events.
 *
 * `message.contentStreaming` (true while `text_delta`s are still arriving
 * for this message, before `message_end`) drives the blinking caret shown
 * after the rendered Markdown so the user gets a visual "still typing" cue.
 *
 * `isRunTail` — true when this is the newest assistant message of an
 * in-flight run — shows the live ticking timer (`LiveRunTimer`, below).
 */
function MessageBubbleImpl({ message, isRunTail }: { message: ChatMessage; isRunTail?: boolean }) {
  const isUser = message.role === "user";

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={cn("flex gap-3", isUser && "flex-row-reverse")}
    >
      <span
        className={cn(
          "flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
          isUser ? "bg-primary text-primary-foreground" : "bg-accent-soft text-accent"
        )}
        aria-hidden="true"
      >
        {isUser ? <User className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5" />}
      </span>

      <div className={cn("min-w-0 max-w-[85%] space-y-2", isUser && "flex flex-col items-end")}>
        {!isUser && message.reasoning && (
          <ReasoningBlock reasoning={message.reasoning} streaming={message.reasoningStreaming} />
        )}

        {!isUser && message.tool_calls.length > 0 && (
          <ToolCallGroup calls={message.tool_calls} />
        )}

        {/* Bubble only when there's real text: `message_start` sets contentStreaming
            before any text_delta, so gating on it alone showed an empty bubble while
            the agent was still reasoning / running tools. */}
        {message.content.trim().length > 0 && (
          <div
            className={cn(
              "rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
              isUser
                ? "rounded-tr-sm bg-primary text-primary-foreground"
                : "rounded-tl-sm bg-card border border-border"
            )}
          >
            {isUser ? (
              <p className="whitespace-pre-wrap">{message.content}</p>
            ) : (
              <div className="prose-chat">
                {/* content is guaranteed non-empty by the render gate above */}
                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                  {message.content}
                </ReactMarkdown>
                {message.contentStreaming && (
                  <span className="blinking-caret" aria-hidden="true" />
                )}
              </div>
            )}
          </div>
        )}

        {/* Run-elapsed indicator (assistant only): frozen total once the run has
            concluded, or a live ticking timer while this message is the run's tail. */}
        {!isUser && message.runElapsedMs != null ? (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Clock className="h-3 w-3" aria-hidden="true" />
            {formatRunDuration(message.runElapsedMs)}
          </span>
        ) : (
          !isUser && isRunTail && <LiveRunTimer />
        )}
      </div>
    </motion.div>
  );
}

// Memoized so a store update affecting one message (e.g. a text_delta
// appending to the last message) doesn't force every prior MessageBubble in
// a long transcript to re-render.
export const MessageBubble = memo(MessageBubbleImpl);

/**
 * Live 1s-ticking elapsed-time readout for the run's tail assistant message.
 * Isolated into its own leaf component so the per-second re-render stays
 * scoped here instead of forcing the (memoized) MessageBubble tree to re-render.
 */
function LiveRunTimer() {
  // Subscribe to the run's start time; re-renders when a new run begins.
  const runStartedAt = useChatStore((s) => s.runStartedAt);
  const [now, setNow] = useState(() => Date.now());

  // Tick once per second while mounted (only mounted for the in-flight run's tail message).
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  if (runStartedAt === null) return null;
  return (
    <span className="flex items-center gap-1 text-xs text-muted-foreground">
      <Clock className="h-3 w-3" aria-hidden="true" />
      {formatRunDuration(now - runStartedAt)}
    </span>
  );
}
