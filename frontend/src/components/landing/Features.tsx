"use client";

import { motion } from "framer-motion";
import { Compass, Users, Workflow, BookMarked } from "lucide-react";

const features = [
  {
    icon: Compass,
    title: "Deep Research",
    description:
      "The agent searches the live web, reads sources, and distills findings before writing a single word.",
  },
  {
    icon: Users,
    title: "Human-in-the-loop Planning",
    description:
      "Review the proposed outline and task plan, request changes, and approve before the agent starts writing.",
  },
  {
    icon: Workflow,
    title: "Visual Curricula",
    description:
      "Explore your curriculum as an interactive, n8n-style workflow — modules and sections come alive as they're written.",
  },
  {
    icon: BookMarked,
    title: "Cited Sources",
    description:
      "Every claim links back to a real source, with footnotes and a sources card at the end of each section.",
  },
];

/** Landing page section: the "everything you need" feature grid (research, HITL planning, visual curricula, citations). */
export function Features() {
  return (
    <section id="features" className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
      <div className="mx-auto max-w-2xl text-center">
        <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
          Everything you need, nothing you have to build
        </h2>
        <p className="mt-3 text-muted-foreground">
          InterviewCraft handles research, planning, and writing so you can focus on
          learning.
        </p>
      </div>
      <div className="mt-12 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {features.map((f, i) => (
          <motion.div
            key={f.title}
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-60px" }}
            transition={{ duration: 0.35, delay: i * 0.08 }}
            className="rounded-xl border border-border bg-card p-5 shadow-sm"
          >
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent-soft text-accent">
              <f.icon className="h-5 w-5" aria-hidden="true" />
            </div>
            <h3 className="mt-4 font-semibold">{f.title}</h3>
            <p className="mt-1.5 text-sm text-muted-foreground">{f.description}</p>
          </motion.div>
        ))}
      </div>
    </section>
  );
}
