"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, ClipboardList, MessageSquareText } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Input";
import type { ProposedPlan } from "@/stores/useChatStore";

interface PlanApprovalCardProps {
  plan: ProposedPlan;
  disabled: boolean;
  onDecision: (decision: "approve" | "modify", feedback: string | null) => void;
}

export function PlanApprovalCard({ plan, disabled, onDecision }: PlanApprovalCardProps) {
  const [feedback, setFeedback] = useState("");
  const [mode, setMode] = useState<"idle" | "requesting">("idle");

  return (
    <motion.div
      initial={{ opacity: 0, y: 12, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.25 }}
      className="rounded-xl border border-accent/30 bg-accent-soft/40 p-4"
    >
      <div className="flex items-center gap-2">
        <ClipboardList className="h-4 w-4 text-accent" aria-hidden="true" />
        <h3 className="text-sm font-semibold">Proposed plan (v{plan.version})</h3>
      </div>

      <div className="prose-chat mt-3 max-h-64 overflow-y-auto rounded-lg bg-card p-3 text-xs scrollbar-thin">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{plan.outline_markdown}</ReactMarkdown>
      </div>

      <ul className="mt-3 max-h-48 space-y-1.5 overflow-y-auto scrollbar-thin">
        {plan.tasks.map((task) => (
          <li key={task.id} className="flex items-start gap-2 rounded-md bg-card/60 px-2.5 py-1.5 text-xs">
            <span
              className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                task.status === "done" ? "border-success bg-success text-white" : "border-border"
              }`}
            >
              {task.status === "done" && <Check className="h-2.5 w-2.5" aria-hidden="true" />}
            </span>
            <div>
              <p className="font-medium">{task.title}</p>
              {task.description && (
                <p className="text-muted-foreground">{task.description}</p>
              )}
            </div>
          </li>
        ))}
      </ul>

      {mode === "requesting" ? (
        <div className="mt-3 space-y-2">
          <Textarea
            autoFocus
            rows={3}
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="What should change about this plan?"
            disabled={disabled}
          />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setMode("idle")} disabled={disabled}>
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={() => onDecision("modify", feedback.trim() || null)}
              disabled={disabled || !feedback.trim()}
            >
              Send feedback
            </Button>
          </div>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" onClick={() => onDecision("approve", null)} disabled={disabled}>
            <Check className="h-3.5 w-3.5" aria-hidden="true" />
            Approve &amp; build
          </Button>
          <Button variant="outline" size="sm" onClick={() => setMode("requesting")} disabled={disabled}>
            <MessageSquareText className="h-3.5 w-3.5" aria-hidden="true" />
            Request changes
          </Button>
        </div>
      )}
    </motion.div>
  );
}
