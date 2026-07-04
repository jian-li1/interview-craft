"use client";

import { motion } from "framer-motion";
import { CheckCircle2, Search, Sparkles, GitBranch } from "lucide-react";

/** Stylized chat + workflow illustration built entirely with divs (no images). */
export function ProductMock() {
  return (
    <div className="relative mx-auto max-w-md rounded-2xl border border-border bg-card p-4 shadow-xl sm:max-w-lg">
      <div className="flex items-center gap-1.5 pb-3">
        <span className="h-2.5 w-2.5 rounded-full bg-destructive/60" />
        <span className="h-2.5 w-2.5 rounded-full bg-warning/60" />
        <span className="h-2.5 w-2.5 rounded-full bg-success/60" />
        <span className="ml-3 text-xs font-medium text-muted-foreground">
          Studio — System Design Interview
        </span>
      </div>

      <div className="grid grid-cols-5 gap-3">
        <div className="col-span-3 space-y-2.5 rounded-xl bg-muted/50 p-3">
          <div className="flex items-center gap-1.5 text-xs font-medium text-accent">
            <motion.span
              animate={{ opacity: [0.4, 1, 0.4] }}
              transition={{ duration: 1.8, repeat: Infinity }}
              className="h-1.5 w-1.5 rounded-full bg-accent"
            />
            Researching
          </div>
          <ChatBubble delay={0.1}>
            Help me prep for a Staff Backend Engineer interview at a fintech startup.
          </ChatBubble>
          <ToolRow icon={Search} label="Searching: fintech backend interview loops" delay={0.3} />
          <ToolRow icon={Search} label="Reading: eng.stripe.com/interviews" delay={0.5} />
          <AssistantTyping delay={0.7} />
        </div>

        <div className="col-span-2 space-y-2">
          <WorkflowNode title="Start" emoji="🚀" delay={0.2} filled />
          <Connector />
          <WorkflowNode title="System Design Basics" delay={0.5} pulsing />
          <Connector />
          <WorkflowNode title="Scalability Patterns" delay={0.8} dashed />
        </div>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 1.1, duration: 0.4 }}
        className="mt-3 flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-xs text-muted-foreground"
      >
        <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
        Plan proposed — 6 modules, 24 sections. Approve to start writing.
      </motion.div>
    </div>
  );
}

function ChatBubble({ children, delay }: { children: React.ReactNode; delay: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay, duration: 0.35 }}
      className="rounded-lg rounded-bl-sm bg-card px-3 py-2 text-xs leading-relaxed shadow-sm"
    >
      {children}
    </motion.div>
  );
}

function ToolRow({
  icon: Icon,
  label,
  delay,
}: {
  icon: typeof Search;
  label: string;
  delay: number;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay, duration: 0.35 }}
      className="flex items-center gap-1.5 rounded-md border border-border bg-card/60 px-2.5 py-1.5 text-[11px] text-muted-foreground"
    >
      <Icon className="h-3 w-3 shrink-0" aria-hidden="true" />
      <span className="truncate">{label}</span>
    </motion.div>
  );
}

function AssistantTyping({ delay }: { delay: number }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ delay }}
      className="flex items-center gap-1 rounded-lg bg-card px-3 py-2 shadow-sm w-fit"
    >
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          animate={{ opacity: [0.2, 1, 0.2] }}
          transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.15 }}
          className="h-1.5 w-1.5 rounded-full bg-muted-foreground"
        />
      ))}
    </motion.div>
  );
}

function WorkflowNode({
  title,
  emoji,
  delay,
  pulsing,
  dashed,
  filled,
}: {
  title: string;
  emoji?: string;
  delay: number;
  pulsing?: boolean;
  dashed?: boolean;
  filled?: boolean;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay, duration: 0.35 }}
      className={`rounded-lg border px-2.5 py-2 text-[11px] font-medium ${
        dashed ? "border-dashed border-border text-muted-foreground" : "border-accent/40"
      } ${filled ? "bg-accent-soft text-accent" : "bg-card"}`}
    >
      <div className="flex items-center gap-1.5">
        {emoji && <span>{emoji}</span>}
        {pulsing && (
          <motion.span
            animate={{ opacity: [0.4, 1, 0.4] }}
            transition={{ duration: 1.4, repeat: Infinity }}
            className="h-1.5 w-1.5 rounded-full bg-accent"
          />
        )}
        {!pulsing && filled && <CheckCircle2 className="h-3 w-3 text-success" aria-hidden="true" />}
        {!pulsing && !filled && <GitBranch className="h-3 w-3" aria-hidden="true" />}
        <span className="truncate">{title}</span>
      </div>
    </motion.div>
  );
}

function Connector() {
  return <div className="ml-3 h-3 w-px bg-border" aria-hidden="true" />;
}
