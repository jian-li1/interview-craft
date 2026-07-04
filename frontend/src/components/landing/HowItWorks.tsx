"use client";

import { motion } from "framer-motion";

const steps = [
  {
    step: "01",
    title: "Tell us what you're preparing for",
    description: "One prompt is enough — a role, a company, a topic, or all three.",
  },
  {
    step: "02",
    title: "The agent researches the web",
    description: "It searches, reads, and takes notes from real, current sources.",
  },
  {
    step: "03",
    title: "You approve the plan",
    description: "Review the proposed outline and tasks, request tweaks, then approve.",
  },
  {
    step: "04",
    title: "Your curriculum comes to life",
    description: "Modules and sections write themselves in, with diagrams and citations.",
  },
];

export function HowItWorks() {
  return (
    <section className="border-y border-border/60 bg-muted/30 px-4 py-20 sm:px-6">
      <div className="mx-auto max-w-6xl">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">How it works</h2>
          <p className="mt-3 text-muted-foreground">From prompt to full curriculum in four steps.</p>
        </div>
        <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {steps.map((s, i) => (
            <motion.div
              key={s.step}
              initial={{ opacity: 0, y: 16 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ duration: 0.35, delay: i * 0.1 }}
              className="relative"
            >
              <span className="text-4xl font-bold text-gradient-accent">{s.step}</span>
              <h3 className="mt-3 font-semibold">{s.title}</h3>
              <p className="mt-1.5 text-sm text-muted-foreground">{s.description}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
