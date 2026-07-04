"use client";

import { memo } from "react";
import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { User, Sparkles } from "lucide-react";
import { ReasoningBlock } from "@/components/studio/chat/ReasoningBlock";
import { ToolCallGroup } from "@/components/studio/chat/ToolCallCard";
import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/stores/useChatStore";

function MessageBubbleImpl({ message }: { message: ChatMessage }) {
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

        {(message.content || message.contentStreaming) && (
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
                <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                  {message.content || " "}
                </ReactMarkdown>
                {message.contentStreaming && (
                  <span className="blinking-caret" aria-hidden="true" />
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}

export const MessageBubble = memo(MessageBubbleImpl);
