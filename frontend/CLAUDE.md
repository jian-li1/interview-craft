# Frontend — AI context

See root `/CLAUDE.md` first. Scoped conventions for `frontend/` only. Full walkthrough:
`docs/guides/frontend.md`. Contract: `docs/specs/03-frontend-spec.md` +
`docs/specs/01-architecture-and-contracts.md` (API/WS shapes).

## Structure map

- `src/app/` — App Router pages. `(app)` route group = authenticated shell
  (`layout.tsx` runs `useAuthGuard({requireAuth:true, requireOnboarding:true})` then
  renders `AppShell`). Public pages (`/`, `/login`) and `/onboarding` live outside it.
- `src/components/auth/` — `AuthProvider` (context around `useAuthStore`, fetches
  `/api/auth/me` once), `GoogleSignInButton`, `useAuthGuard`.
- `src/components/layout/` — `AppShell`, `Sidebar`, `PublicNavbar`, `UserMenu`,
  `ThemeProvider`/`ThemeToggle`.
- `src/components/studio/chat/` — `ChatPanel`, `Composer`, `MessageBubble`,
  `PhaseBanner`, `PlanApprovalCard`, `ReasoningBlock`, `ToolCallCard`.
- `src/components/studio/curriculum/` — `CurriculumPanel`, `WorkflowView` (React Flow),
  `ReaderView`, `SectionContent`, `MermaidDiagram`, `SourcesCard`, `ActivityFeed`,
  `nodes/`, `edges/`.
- `src/components/ui/` — hand-rolled primitives (no Radix/shadcn): `Button`, `Card`,
  `Input`, `Select`, `Tabs`, `ChipInput`, `ChipSelect` (model/search-provider chip
  popover, moved here from `studio/chat/ComposerSelect.tsx` once the dashboard
  `PromptBox` grew its own chips — shared by both), `ConfirmDialog`, `EmptyState`,
  `Skeleton`, `Badge`. Match this style for any new primitive.
- `src/lib/` — `api.ts` (fetch wrapper), `ws.ts` (`ChatSocket`), `env.ts`, `types.ts`
  (mirrors every spec-01 shape), `utils.ts` (`cn`, `timeAgo`, `initials`).
- `src/hooks/useChatSocket.ts` — owns the `ChatSocket` lifecycle + the entire
  WS-event-to-store dispatch table.
- `src/stores/` — `useAuthStore`, `useChatStore`, `useCurriculumStore` (Zustand).

## Conventions

- **Styling**: semantic Tailwind tokens only (`bg-background`, `text-foreground`,
  `bg-card`, `text-muted-foreground`, `bg-accent`, `bg-primary`, `bg-destructive`, etc.
  — defined in `src/app/globals.css` via `@theme inline` over `:root`/`.dark` CSS
  custom properties). Never hardcode a hex color; both themes must stay correct free.
- **`cn()`** (`src/lib/utils.ts`, clsx + tailwind-merge) for all conditional/merged
  className logic — don't hand-roll className string concatenation.
- **Zustand store pattern**: one store per concern (`useAuthStore` = session,
  `useChatStore` = one active conversation, `useCurriculumStore` = one active
  curriculum). Actions are plain store functions, not hooks. Prefer extending an
  existing store over adding a new one.
- **`ssr:false` rule (non-negotiable)**: any component touching `mermaid` or
  `@xyflow/react` must never be statically imported into a server-rendered tree. Use
  `next/dynamic(() => import(...), { ssr: false })` at the component boundary (see
  `CurriculumPanel.tsx`), or a runtime `import(...)` inside a `useEffect` for a plain
  library call (see `MermaidDiagram.tsx`). A static top-level import breaks the build.
- **API calls**: always go through `lib/api.ts`'s `apiFetch`/the `*Api` namespaces —
  never call `fetch` directly. Guarantees `credentials: "include"`, the
  `X-Requested-With` CSRF header on mutating calls, and consistent 401 handling.
- **New page**: place under `src/app/`; if it needs the authenticated shell, put it
  under the `(app)` route group to inherit the auth+onboarding guard for free.

## How WS events map to store actions

Dispatched in `src/hooks/useChatSocket.ts` (the single place this mapping lives — don't
add a second WS listener elsewhere): `session_ready`→`setCurriculumId` +
`setAgentRunning(agent_running)` + `setModelOptions(available_models, selected_model,
search_providers, search_provider)` (hydrates the composer's model/search chips),
`message_start`→`startMessage`, `reasoning_delta`→`appendReasoningDelta`,
`text_delta`→`appendTextDelta`, `tool_call_start`→`startToolCall`,
`tool_call_result`→`resolveToolCall`, `message_end`→`endMessage`,
`phase_change`→`setPhase`, `progress`→`setProgress`, `plan_proposed`→`proposePlan` (all
on `useChatStore`); `curriculum_updated`→`useCurriculumStore.refetch` (a **different**
store — REST refetch, not a chat-store field); `compaction_start`→`startCompaction`,
`compaction`→`finishCompaction` (renders/resolves the inline transcript chip — no longer
toast-only), `context_usage`→`setContextUsage` (drives the composer's warning card);
`error` → toast only (also calls `finishRunTiming()` + `setAgentRunning(false)` if not
recoverable); `agent_done`→`finishRunTiming(elapsed_ms)` + `setAgentRunning(false)`
(`agent_done` is the sole authority for clearing `agentRunning` — `endMessage` no longer
touches it, since `message_end` fires between ReAct iterations mid-run); `pong` → no-op.

When adding a new server event type: add it to `ServerEvent` in `lib/types.ts`, add a
case in `useChatSocket.ts`'s dispatch, then add/extend the store action — in that
order, so a type error surfaces immediately if shapes don't match what the backend
sends (cross-check `docs/specs/01-architecture-and-contracts.md` §7 and
`backend/app/ws/chat.py`/`orchestrator.py` for the authoritative payload shape).

## Verify

```bash
npm run build   # must pass with zero TypeScript errors — this is the correctness gate
npm run dev     # local dev server, http://localhost:3000
```

No test runner is configured (no jest/vitest/playwright) — the build's type-checking is
the enforced bar for this codebase.
