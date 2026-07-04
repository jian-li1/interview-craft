"use client";

import { motion } from "framer-motion";
import { ArrowDown } from "lucide-react";

export function ScrollToBottomPill({ onClick }: { onClick: () => void }) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 8 }}
      aria-label="Scroll to latest messages"
      className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-xs font-medium shadow-md hover:bg-muted"
    >
      <ArrowDown className="h-3.5 w-3.5" aria-hidden="true" />
      New messages
    </motion.button>
  );
}
