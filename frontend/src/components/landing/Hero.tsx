"use client";

import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ProductMock } from "@/components/landing/ProductMock";
import { useRouter } from "next/navigation";

/** Landing page section: above-the-fold hero with headline, CTA buttons (both route to /login), and the `ProductMock` illustration. */
export function Hero() {
  const router = useRouter();
  return (
    <section className="relative overflow-hidden px-4 pb-20 pt-16 sm:px-6 sm:pt-24 lg:pt-28">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 -top-32 -z-10 flex justify-center blur-3xl"
      >
        <div className="h-72 w-[42rem] bg-gradient-accent opacity-20" />
      </div>

      <div className="mx-auto max-w-6xl">
        <div className="grid items-center gap-12 lg:grid-cols-2">
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: "easeOut" }}
          >
            <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground">
              Agentic interview prep, built for you
            </span>
            <h1 className="mt-5 text-4xl font-bold tracking-tight sm:text-5xl lg:text-[3.25rem] lg:leading-[1.05]">
              A complete interview curriculum,{" "}
              <span className="text-gradient-accent">written by an agent</span>{" "}
              that actually researches
            </h1>
            <p className="mt-5 max-w-xl text-lg text-muted-foreground">
              Describe the interview you&apos;re preparing for. InterviewBlueprint researches
              the role deeply, proposes a plan you approve, then writes a full,
              beginner-friendly curriculum with diagrams, sample Q&amp;A, and cited sources.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Button size="lg" onClick={() => router.push("/login")}>
                Start preparing free
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Button>
              <Button size="lg" variant="outline" onClick={() => router.push("/login")}>
                See how it works
              </Button>
            </div>
            <div className="mt-8 flex items-center gap-6 text-sm text-muted-foreground">
              <div>
                <p className="text-lg font-semibold text-foreground">Deep research</p>
                <p>Live web sources, not guesses</p>
              </div>
              <div className="h-8 w-px bg-border" />
              <div>
                <p className="text-lg font-semibold text-foreground">You&apos;re in control</p>
                <p>Approve the plan first</p>
              </div>
            </div>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, ease: "easeOut", delay: 0.1 }}
          >
            <ProductMock />
          </motion.div>
        </div>
      </div>
    </section>
  );
}
