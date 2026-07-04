"use client";

import { motion } from "framer-motion";
import { PromptBox } from "@/components/dashboard/PromptBox";
import { CurriculumGrid } from "@/components/dashboard/CurriculumGrid";
import { useAuth } from "@/components/auth/AuthProvider";

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export default function DashboardPage() {
  const { user } = useAuth();
  const firstName = user?.name?.split(" ")[0] ?? "there";

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-6 lg:py-14">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
      >
        <h1 className="text-2xl font-semibold sm:text-3xl">
          {greeting()}, {firstName}
        </h1>
        <p className="mt-1.5 text-muted-foreground">
          Ready to prep for your next interview?
        </p>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.05 }}
        className="mt-8"
      >
        <PromptBox />
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.1 }}
        className="mt-10"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Your curricula</h2>
        </div>
        <CurriculumGrid />
      </motion.div>
    </div>
  );
}
