"use client";

import { createContext, useContext, useId, useState } from "react";
import { cn } from "@/lib/utils";
import { motion } from "framer-motion";

interface TabsContextValue {
  value: string;
  setValue: (value: string) => void;
  name: string;
}

const TabsContext = createContext<TabsContextValue | null>(null);

/**
 * Hand-rolled Tabs primitive family (no Radix): `Tabs` (context provider,
 * supports both uncontrolled via `defaultValue` and controlled via
 * `value`/`onValueChange`), `TabsList` (the `role="tablist"` pill
 * container), `TabsTrigger` (a `role="tab"` button that also renders the
 * shared animated active-tab background using a Framer Motion `layoutId`
 * scoped by `useId()` so multiple `Tabs` instances on one page don't
 * collide), and `TabsContent` (renders its children only when its `value`
 * matches the active tab). `TabsTrigger`/`TabsContent` must be rendered
 * inside a `Tabs` provider or they throw.
 */
export function Tabs({
  defaultValue,
  value: controlledValue,
  onValueChange,
  children,
  className,
}: {
  defaultValue?: string;
  value?: string;
  onValueChange?: (value: string) => void;
  children: React.ReactNode;
  className?: string;
}) {
  const [internal, setInternal] = useState(defaultValue ?? "");
  const name = useId();
  const value = controlledValue ?? internal;
  const setValue = (v: string) => {
    setInternal(v);
    onValueChange?.(v);
  };
  return (
    <TabsContext.Provider value={{ value, setValue, name }}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  );
}

export function TabsList({ children, className, "aria-label": ariaLabel }: { children: React.ReactNode; className?: string; "aria-label"?: string }) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        "relative inline-flex items-center gap-1 rounded-lg bg-muted p-1",
        className
      )}
    >
      {children}
    </div>
  );
}

export function TabsTrigger({
  value,
  children,
  className,
}: {
  value: string;
  children: React.ReactNode;
  className?: string;
}) {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error("TabsTrigger must be used within Tabs");
  const active = ctx.value === value;
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={() => ctx.setValue(value)}
      className={cn(
        "relative z-0 rounded-md px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active ? "text-accent-foreground" : "text-muted-foreground hover:text-foreground",
        className
      )}
    >
      {active && (
        <motion.span
          layoutId={`tabs-active-${ctx.name}`}
          className="absolute inset-0 -z-10 rounded-md bg-card shadow-sm"
          transition={{ type: "spring", duration: 0.4, bounce: 0.2 }}
        />
      )}
      {children}
    </button>
  );
}

export function TabsContent({
  value,
  children,
  className,
}: {
  value: string;
  children: React.ReactNode;
  className?: string;
}) {
  const ctx = useContext(TabsContext);
  if (!ctx) throw new Error("TabsContent must be used within Tabs");
  if (ctx.value !== value) return null;
  return (
    <div role="tabpanel" className={className}>
      {children}
    </div>
  );
}
