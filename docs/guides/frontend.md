# Frontend deep-dive

A full walkthrough of `frontend/` — the Next.js 15 App Router client. Complements
[docs/specs/03-frontend-spec.md](../specs/03-frontend-spec.md) (the intended UX) with
"how it's actually implemented" detail: real file paths, component/hook/store names, and
exact WS-event-to-store wiring. See [backend.md](backend.md) and
[agent-system.md](agent-system.md) for the server side this UI talks to.

## 1. Routing & layout structure

App Router tree under `frontend/src/app/`:

```
app/layout.tsx                          Root layout (fonts, ThemeProvider, AuthProvider, Toaster)
app/page.tsx                            "/" — public landing
app/login/page.tsx                      "/login" — public
app/onboarding/page.tsx                 "/onboarding" — auth required, no onboarding gate
app/(app)/layout.tsx                    Route group: auth guard + AppShell
app/(app)/dashboard/page.tsx            "/dashboard"
app/(app)/settings/page.tsx             "/settings"
app/(app)/studio/[conversationId]/page.tsx   "/studio/[id]" — THE WORKSPACE
```

**`app/layout.tsx`** loads `Inter` via `next/font/google` bound to CSS variable
`--font-sans-var`, wraps the tree in `ThemeProvider` (`attribute="class"`,
`defaultTheme="system"`, `enableSystem`, `disableTransitionOnChange`) → `AuthProvider` →
`children`, plus a global `<Toaster richColors position="top-right" closeButton />`
from `sonner`. `<html suppressHydrationWarning>` is required by `next-themes` to avoid a
hydration-mismatch warning on the class attribute.

**`app/(app)/layout.tsx`** calls `useAuthGuard({ requireAuth: true, requireOnboarding:
true })` then renders `AppShell` (§3) around `children` — this is the single choke point
enforcing both "must be logged in" and "must have finished onboarding" for every page
under `/dashboard`, `/settings`, `/studio/*`.

**`app/login/page.tsx`** is a client component using `useAuthGuard({ redirectIfAuthed:
true })` — if already authenticated it redirects away from the login page rather than
showing it.

**`app/onboarding/page.tsx`** is a client component implementing the 4-step wizard
(`TOTAL_STEPS = 4`), guarded by `useAuthGuard({ requireAuth: true })` (deliberately
*without* `requireOnboarding`, since this page's whole job is to satisfy that gate).
Local state: `step`, `profile: ProfileIn`, `resumeFilename`, `resumeText`,
`synthesizedProfile`, `direction` (drives the slide direction of the Framer Motion step
transition). Steps: background/bio → target roles + experience + timeline → skills +
goals + learning style + `ResumeDropzone` → review + "Generate my profile" (calls
`onboardingApi.synthesize()`) → finish routes to `/dashboard`.

**`app/(app)/studio/[conversationId]/page.tsx`** unwraps the Next 15 async `params`
promise via `use(params)`. On mount / whenever `conversationId` changes: resets both the
chat and curriculum Zustand stores, sets the new `conversationId`, then fetches
`conversationsApi.messages(conversationId)` and calls `hydrateHistory(messages)`.
`useIsMobile()` returns `boolean | null`; while `null` it renders an empty placeholder to
avoid a layout flash before the viewport check resolves. Desktop: drag-resizable flex
split — chat panel width comes from `usePanelResize` (`src/hooks/usePanelResize.ts`, a
shared hook also used by `ReaderView`'s TOC sidebar), default 480px, lazily initialized
from `localStorage` key `ic:studio-chat-width`, clamped to `[340, min(720, 0.6 *
innerWidth)]`; the returned `separatorProps` spread onto a `role="separator"` divider
handle pointer drag (`setPointerCapture` on `pointerdown`, width recomputed on
`pointermove`, persisted to `localStorage` on `pointerup`/`pointercancel`) and
ArrowLeft/ArrowRight keyboard nudges (24px/step, same clamp+persist); curriculum panel
stays `flex-1`. Both panel wrappers get `pointer-events-none` while dragging so the React
Flow canvas/chat can't swallow the pointer stream mid-drag. Mobile: a `Tabs` switcher
between "chat" and "curriculum" where **only one subtree is mounted at a time** (an
explicit choice to avoid double-mounting React Flow / Mermaid instances).
`handleExplain(prompt)` — wired up from `SectionContent`'s per-heading "Explain" button
through `CurriculumPanel` — prefills the chat composer and, on mobile, switches the
active tab to "chat". The curriculum panel header has a full-screen "focus mode" toggle
(`useCurriculumStore.focusMode`, toggled via `CurriculumPanel`, also exits on Escape
unless a modal is open) that CSS-hides the app header/sidebar/chat column so the
curriculum panel fills the viewport; force-cleared on the studio page's unmount as a
safety net (see `AppShell.tsx`, `CurriculumPanel.tsx`).

## 2. Auth guard flow

```mermaid
sequenceDiagram
    participant P as Any protected page
    participant AP as AuthProvider context
    participant Store as useAuthStore
    participant API as GET /api/auth/me

    Note over AP: mounted once at the root layout
    AP->>Store: fetchMe, guarded by a hasFetched ref against StrictMode double-invoke
    Store->>API: authApi.me with skipAuthRedirect true
    alt 200 response
        API-->>Store: UserOut
        Store->>Store: set user, initialized true, loading false
    else 401 or network error
        API-->>Store: no redirect, since skipAuthRedirect
        Store->>Store: user null, initialized true, loading false
    end
    P->>P: useAuthGuard with requireAuth, requireOnboarding, redirectIfAuthed options
    P->>P: wait until initialized is true and loading is false
    alt redirectIfAuthed and user present
        P->>P: router to /dashboard or /onboarding
    else requireAuth and no user
        P->>P: router to /login
    else requireAuth, user present, requireOnboarding, onboarding incomplete
        P->>P: router to /onboarding
    else
        P->>P: render page
    end
```

- **`components/auth/AuthProvider.tsx`** — a React Context around `useAuthStore`,
  exposing `useAuth() -> { user, loading, initialized, refresh }`. Fetches `/api/auth/me`
  exactly once (a `hasFetched` ref survives React 19 StrictMode's double-invoke of
  effects in dev).
- **`components/auth/useAuthGuard.ts`** — options `requireAuth`, `requireOnboarding`,
  `redirectIfAuthed` (all default `false`). Returns `{ user, ready }` where `ready =
  initialized && !loading`. Every redirect decision is deferred until `ready` to avoid
  redirect flicker before the `/api/auth/me` call resolves.
- **`stores/useAuthStore.ts`** (Zustand) — `{ user: UserOut | null, loading: boolean
  (starts true), initialized: boolean (starts false) }` plus actions `fetchMe()`,
  `setUser(user)`, `logout()` (calls `authApi.logout()`, clears `user` in a `finally` so
  the UI reflects logged-out state even if the server call fails).
- **`components/auth/GoogleSignInButton.tsx`** — props `{ onCredential: (idToken:
  string) => void; disabled?: boolean }`. Dynamically injects the Google Identity
  Services script (`https://accounts.google.com/gsi/client`) if not already present,
  then calls `window.google.accounts.id.initialize({ client_id, callback, ux_mode:
  "popup" })` and `renderButton` (outline theme, pill shape, width 320, "continue_with"
  text). Renders a warning box if `env.googleClientId` is empty and an error box if the
  script fails to load — both are useful signals while debugging OAuth client
  misconfiguration (see [setup-local.md](setup-local.md)'s troubleshooting section).

`login/page.tsx`'s credential handler calls `authApi.loginWithGoogle(idToken)`, sets the
returned user into `useAuthStore`, then routes to `/dashboard` or `/onboarding`
depending on `user.onboarding_completed` — the same decision `useAuthGuard` would make,
duplicated here to avoid an extra render before the store updates.

## 3. Theming system

Tailwind v4, `next-themes` with the class strategy. Semantic tokens are defined as CSS
custom properties in `frontend/src/app/globals.css`: `:root` holds the light values,
`.dark` overrides them (the dark-mode selector itself is declared via `@custom-variant
dark (&:where(.dark, .dark *))`, matching `next-themes`'s `attribute="class"` output),
and a `@theme inline` block maps them to Tailwind's `--color-*` namespace — this is what
makes utility classes like `bg-background`, `text-foreground`, `bg-card`,
`text-card-foreground`, `bg-popover`, `border-border`, `bg-input`, `ring-ring`,
`bg-muted`, `text-muted-foreground`, `bg-accent`, `text-accent-foreground`,
`bg-accent-soft`, `bg-primary`, `text-primary-foreground`, `bg-secondary`,
`text-secondary-foreground`, `bg-success`, `bg-warning`, `bg-destructive`,
`text-destructive-foreground`, and `bg-info` all resolve correctly in both themes.
`--radius-xl/lg/md/sm` and `--font-sans` (bound to `--font-sans-var`) are defined the
same way. Custom utility classes layered on top: `.bg-gradient-accent` /
`.text-gradient-accent` (3-stop gradient via `--gradient-from/via/to`),
`.scrollbar-thin`, `.shimmer` / `.shimmer-text` (loading shimmer + the "Thinking…" label
animation), `.blinking-caret` (the streaming-text caret), `.prose-chat` / `.prose-reader`
(hand-rolled markdown typography — no `@tailwindcss/typography` plugin is used),
`.mermaid-container svg { max-width: 100% }`, and `.react-flow__attribution { display:
none }` (belt-and-suspenders alongside React Flow's own `proOptions={{
hideAttribution: true }}`).

- **`components/layout/ThemeProvider.tsx`** — a thin re-export of `next-themes`'s
  `ThemeProvider`.
- **`components/layout/ThemeToggle.tsx`** — uses `useTheme()`, guards against a
  hydration mismatch with a `mounted` state (renders an empty placeholder until the
  first client effect runs), and toggles directly between `"light"`/`"dark"` (it does
  not cycle through `"system"` — that's only reachable from the Appearance settings
  tab).

One real inconsistency worth knowing about: `globals.css` unconditionally imports
`highlight.js/styles/github-dark.css` for `rehype-highlight` code blocks, so fenced code
in curriculum sections renders with dark syntax colors even when the app itself is in
light mode.

## 4. Pages

- **Landing (`app/page.tsx`)** — `PublicNavbar` + `Hero` + `Features` + `HowItWorks` +
  `Footer` (all in `components/landing/`). `PublicNavbar`'s Login/Get Started buttons
  use a hard `window.location.href` navigation rather than `next/navigation`'s router —
  inconsistent with the rest of the app's client-side routing, but harmless.
- **Login (`app/login/page.tsx`)** — see §2.
- **Onboarding (`app/onboarding/page.tsx`)** — see §1.
- **Dashboard (`app/(app)/dashboard/page.tsx`)** — a time-of-day `greeting()` helper,
  `PromptBox` (textarea, a bottom chip row with model/search-provider `ChipSelect`s —
  options fetched once on mount via `modelsApi.get()` since there's no WS connection yet,
  rendered only when non-empty — plus example-prompt chips below the box; submitting
  calls `conversationsApi.create({ curriculum_prompt, selected_model?, search_provider? })`
  then routes to `/studio/{id}`), and
  `CurriculumGrid` (fetches `curriculaApi.list()` on mount **and polls every 8000ms** via
  `setInterval` for live status/progress updates — a second, independent update
  mechanism from the WS-driven live updates used inside Studio, since the dashboard has
  no open WS connection of its own). `CurriculumCard` maps `CurriculumStatus` to a
  label/Badge-variant via a `STATUS_META` dict, shows a progress bar for
  `researching|planning|writing|reviewing`, and wraps delete in a `ConfirmDialog`.
- **Settings (`app/(app)/settings/page.tsx`)** — a custom (non-Radix) `Tabs` component
  with three tabs: `ProfileTab` (read-only profile display, "Edit background" links to
  `/onboarding`), `AppearanceTab` (light/dark/system), `AccountTab` (email + logout). No
  more `PreferencesTab` — LLM model / search provider selection moved to the chat
  composer's chips (per-conversation, see §5.4 below), not a settings page.

## 5. The Studio (`app/(app)/studio/[conversationId]/page.tsx`)

### 5.1 `ChatSocket` — `lib/ws.ts`

A small class managing one WebSocket connection with reconnect/backoff, keepalive, and
typed send/receive helpers. Connection states: `"idle" | "connecting" | "open" |
"reconnecting" | "closed"`.

- **URL**: `` `${env.wsBaseUrl}/ws/chat/${conversationId}` `` (`env.wsBaseUrl` defaults
  to `ws://localhost:8000`, from `NEXT_PUBLIC_WS_BASE_URL`).
- **Reconnect/backoff** (exact algorithm): `BASE_BACKOFF_MS = 500`, `MAX_BACKOFF_MS =
  15_000`. On each scheduled reconnect attempt: `backoff = Math.min(BASE_BACKOFF_MS *
  2 ** attempt, MAX_BACKOFF_MS)`, then jitter `Math.random() * 0.3 * backoff` is
  **added on top** (so the actual delay can exceed 15s by up to ~30%, capping practically
  around 19.5s). `reconnectAttempt` increments every scheduled attempt and resets to 0
  on a successful `onopen`. Reconnection is skipped entirely if `.close()` was called
  explicitly (`manuallyClosed` flag).
- **Keepalive**: sends `{type: "ping"}` every `PING_INTERVAL_MS = 25_000` starting at
  `onopen`; the interval is cleared on any close.
- `onerror` is intentionally a no-op — `onclose` is the single place that decides
  whether to reconnect, avoiding duplicate reconnect scheduling from both handlers
  firing.
- Public surface: `connect()`, `close()`, `onEvent(handler)`, `onStateChange(handler)`,
  `getState()`, `send(event)`, plus typed helpers `sendUserMessage(content, model?,
  searchProvider?)`, `sendPlanDecision(decision, feedback, model?, searchProvider?)`,
  `sendStop()`, `sendCompact(model?, searchProvider?)`. The optional `model`/
  `searchProvider` args are the composer's chip selections (§5.4) — included on the
  frame only when set, so the backend falls through to its own resolution when omitted.

### 5.2 `useChatSocket` — `hooks/useChatSocket.ts`

Owns the `ChatSocket` instance's lifecycle keyed on `conversationId` (creates/tears down
on change or unmount) and contains the **entire WS-event-to-store dispatch table**:

| WS event | Store action invoked | Effect |
|---|---|---|
| `session_ready` | `setCurriculumId(curriculum_id)`; `setAgentRunning(agent_running)`; `setModelOptions(available_models, selected_model, search_providers, search_provider)` | the third action hydrates the composer's model/search chip option lists + current selection (§5.4) |
| `message_start` | `startMessage(message_id)` | appends a new assistant message (idempotent on repeat id), sets `agentRunning: true` |
| `reasoning_delta` | `appendReasoningDelta(id, delta)` | appends to `reasoning`, `reasoningStreaming: true` |
| `text_delta` | `appendTextDelta(id, delta)` | appends to `content`, `contentStreaming: true` |
| `tool_call_start` | `startToolCall(messageId, toolCallId, name, input)` | pushes a `running` tool-call record onto the message, prepends an activity-feed item |
| `tool_call_result` | `resolveToolCall(messageId, toolCallId, outputFull, outputPreview, status, elapsedMs)` | updates the tool call and matching activity item's status/detail (`outputFull` = complete result stored on the message record; `outputPreview` = short slice kept on the activity feed). **`elapsedMs` is accepted but discarded — never stored** (see discrepancy below). |
| `message_end` | `endMessage(id)` | clears both streaming flags, `agentRunning: false` |
| `phase_change` | `setPhase(phase, label)` | |
| `progress` | `setProgress(completed, total, detail)` | |
| `plan_proposed` | `proposePlan(plan)` | sets `plan`, `planAwaitingDecision: true` |
| `user_input_requested` | `askQuestion(question, options)` | sets `pendingQuestion: { question, options }` |
| `curriculum_updated` | `useCurriculumStore.refetch({scope, moduleId, sectionId})` | a *different* store — refetches the full curriculum from REST |
| `compaction_start` | `startCompaction()` | appends a "running" `CompactionItem` chip (no-op if one is already running) |
| `compaction` | `finishCompaction(summary, tokensBefore, tokensAfter, compactedThrough)` | resolves the running chip in place with the full rolling summary, or (reconnect replay) appends an already-done chip, deduped by `compactedThrough` |
| `context_usage` | `setContextUsage(tokens, limit, threshold)` | drives the composer's context-usage warning card |
| `agent_done` | `finishRunTiming(elapsed_ms); setAgentRunning(false)` | |
| `error` | none directly | `toast.error(message)`; if `!recoverable`, also `finishRunTiming()` (local-fallback stamp) + `setAgentRunning(false)` |
| `pong` | none | no-op |

`useChatSocket` also drives connection-state toasts: a persistent `toast.loading(
"Reconnecting…", {id: "ws-reconnect"})` while `connectionState === "reconnecting"`, and
on a successful reopen either `toast.success("Reconnected", {id: "ws-reconnect"})` (if
it actually had been reconnecting) or a silent dismiss.

### 5.3 Stores

**`stores/useChatStore.ts`** shape:

```ts
conversationId, curriculumId: string | null
messages: ChatMessage[]   // { id, role, content, reasoning, reasoningStreaming, contentStreaming, tool_calls, created_at, seq }
phase, phaseLabel: string | null
progress: { completed, total, detail } | null
plan: ProposedPlan | null            // { outline_markdown, tasks, version }
planAwaitingDecision: boolean
pendingQuestion: PendingQuestion | null  // { question, options } — request_user_input HITL gate
agentRunning: boolean
activity: ActivityItem[]             // capped at 30, most-recent-first
connectionState: "idle" | "connecting" | "open" | "reconnecting" | "closed"
compactions: CompactionItem[]        // { id, status: "running"|"done", summary (full text),
                                      //   tokensBefore, tokensAfter, afterMessageId,
                                      //   compactedThrough (dedupe key) }
contextUsage: { tokens, limit, threshold } | null
availableModels: ModelOption[]       // { id, provider: "openai"|"gemini" }[] — composer's model-chip options
selectedModel: string | null         // composer's current model-chip selection
searchProviders: string[]            // composer's search-chip options
selectedSearchProvider: string | null  // composer's current search-chip selection
```

Additional actions beyond the event table above: `addUserMessage(content)` (optimistic
local echo with a synthetic `local-{timestamp}-{random}` id, sent before the server's
own message arrives), `hydrateHistory(messages)` (maps `MessageOut[]` from `GET
/api/conversations/{id}/messages` into `ChatMessage[]`, sorted by `seq` — this is what
repopulates the chat on page load/refresh), `resolvePlan()` (clears
`planAwaitingDecision` when the user submits a decision — a store-local action, **not**
triggered by any WS event, since the actual pause-lift only happens once the backend
starts a new turn), `resolveQuestion()` (same pattern as `resolvePlan()`, clears
`pendingQuestion` once the user answers the question card), `reset()` (clears everything
except the ids — including `compactions`/`contextUsage`/`availableModels`/
`selectedModel`/`searchProviders`/`selectedSearchProvider`), `setConnectionState`,
`setModelOptions(models, selectedModel, searchProviders, searchProvider)` (called from
`session_ready`), `setSelectedModel(id)`/`setSelectedSearchProvider(name)` (local-only —
called from the composer chips' `onChange`; no WS frame is sent on selection, the value
is just attached to the next `user_message`/`plan_decision`/`compact` frame).

**`stores/useCurriculumStore.ts`** shape: `{ curriculum: CurriculumFull | null, currentId:
string | null, loading, error, lastUpdatedScope: {scope, moduleId?, sectionId?} | null }`.
`currentId` tracks which curriculum id is "current" independent of whether `curriculum`
has loaded yet. `fetchCurriculum(id)` sets `currentId` synchronously and — if `id` differs
from the previous `currentId` — clears `curriculum`/`lastUpdatedScope` immediately, so a
previously-loaded curriculum never renders while a different one is being fetched; once
the awaited `GET /api/curricula/{id}` resolves (success or error), the result is only
committed if `get().currentId` still equals `id` (guards against out-of-order responses
when switching curricula quickly). `refetch(scope?)` reads `currentId` (not
`curriculum?.id`) and bails silently if there's no current id — it works even while
`curriculum` is still null mid-load, which matters because a `curriculum_updated` WS event
can arrive during the initial fetch. `CurriculumPanel` resets its local `view`/
`activeSelection` state whenever `curriculumId` changes, in addition to the store clearing
`curriculum`, so switching curricula never leaves the Reader showing a stale section.

### 5.4 Chat panel components (`components/studio/chat/`)

- **`ChatPanel.tsx`** — props `{ conversationId, socketRef, historyLoading,
  historyError, prefillText?, onPrefillConsumed? }`. Manages the composer draft and
  auto-scroll (tracks whether the user scrolled up more than 80px from the bottom to
  decide whether to show `ScrollToBottomPill` instead of auto-scrolling).
  `composerDisabled = compacting || planAwaitingDecision || pendingQuestion !== null ||
  connectionState !== "open"`, with a cause-specific `disabledPlaceholder` in the same
  precedence order ("Auto-compacting conversation…" first). Render order: `PhaseBanner` →
  a reconnecting banner (if `connectionState === "reconnecting"`) → message list
  (empty/loading/error states, else an `AnimatePresence` list interleaving
  `MessageBubble`s with `CompactionChip`s — grouped by `afterMessageId` via a `useMemo`'d
  `Map`, chips whose anchor id is null or not (yet) present in `messages` render before
  the first message) → `PlanApprovalCard` (when a plan awaits a decision) → `QuestionCard`
  (when a `request_user_input` gate awaits an answer and no plan card is showing) →
  `ScrollToBottomPill` → `Composer` (passed `contextUsage`, `onCompact`,
  `compacting = compactions.some(c => c.status === "running")`, and the
  `availableModels`/`selectedModel`/`onModelChange`/`searchProviders`/
  `selectedSearchProvider`/`onSearchProviderChange` chip props read straight off
  `useChatStore`). `handleSend`/`handlePlanDecision`/`handleQuestionAnswer`/
  `handleCompact` all forward `selectedModel ?? undefined`/`selectedSearchProvider ??
  undefined` into the corresponding `ChatSocket` send method.
- **`Composer.tsx`** — a single outlined box, column layout: an auto-growing textarea on
  top (height capped at 200px), Enter sends (Shift+Enter inserts a newline), then a
  bottom row with the model/search-provider chips on the left, a flexible spacer, and the
  send/stop button (swaps to stop while `running`) on the right. Optional
  `contextUsage`/`onCompact`/`compacting` props render a warning card attached to the top
  of the input box (shares its rounding, swapping `rounded-xl`→`rounded-b-xl`) once
  `tokens/limit >= 0.7` (`CONTEXT_WARN_FRACTION`): "Context X% full", an explanation that
  auto-compaction fires at `threshold` (80%), and a "Compact now" button (disabled while
  `running || compacting`, sending `compact` via `onCompact`).
- **`components/ui/ChipSelect.tsx`** — the hand-rolled chip-select primitive backing the
  model and search-provider chips in both the studio composer and the dashboard
  `PromptBox` (moved here from `studio/chat/ComposerSelect.tsx` once the dashboard grew
  its own chips, so it lives with the other `components/ui/` primitives): a compact pill
  button (icon + current label + chevron) that opens an UPWARD-anchored popover
  (`absolute bottom-full`, since both host surfaces sit at the bottom of their column and
  a downward popover would be clipped) listing options with a check mark on the
  selection and an optional right-aligned muted badge (used for the model chip's
  `openai`/`gemini` provider tag); closes on outside click, Escape, or picking an option;
  disabled (non-interactive, reduced opacity) whenever the host composer/box is disabled.
  Both the trigger and popover option rows hover to `accent-soft` (not a raw `bg-accent`
  fill, which is unreadable against the chip's muted text in both themes). The module
  also exports `SEARCH_PROVIDER_LABELS` (duckduckgo → "DuckDuckGo", google → "Google",
  tavily → "Tavily", falling back to the raw id) so both call sites share one mapping.
- **`CompactionChip.tsx`** — full-width divider chip (`hairline — pill — hairline`)
  rendered by `ChatPanel`'s interleaving logic; `"running"` shows a spinner + "Auto-
  compacting conversation…", `"done"` shows a fold icon + "Auto-compacted" + a
  `formatTokens` before/after detail (omitted when `tokensBefore` is 0/null — legacy
  reconnect replays), and — only when `summary` is non-empty — is itself a button that
  expands an `AnimatePresence` panel showing the FULL rolling summary in a scroll-capped
  (`max-h-60 overflow-y-auto`) pane styled like `ReasoningBlock`'s, with the "Summary of
  compacted history" caption pinned above the scrolling region.
- **`MessageBubble.tsx`** (`memo`-wrapped) — renders an avatar, `ReasoningBlock` (if
  `reasoning` present, assistant only), a `ToolCallGroup` (if any tool calls, assistant
  only), then the content: plain `whitespace-pre-wrap` text for user messages,
  `ReactMarkdown` (remark-gfm + rehype-highlight) for assistant messages, with a
  `blinking-caret` span appended while `contentStreaming`.
- **`PhaseBanner.tsx`** — maps `phase` to a lucide icon (`PHASE_ICONS`: research→Search,
  planning→ListChecks, awaiting_approval→Compass, writing→PenLine, ready→CheckCircle2,
  default→Sparkles), stops the spin animation once `phase === "ready"`, shows a progress
  bar when `progress.total > 0`.
- **`PlanApprovalCard.tsx`** — renders `outline_markdown` (ReactMarkdown+remark-gfm) and
  a task checklist (checkmark when `status === "done"`); toggles between an idle
  [Approve & build]/[Request changes] row and a feedback-textarea row, calling
  `onDecision(decision, feedback)` which the page wires to `socket.sendPlanDecision(...)`.
- **`QuestionCard.tsx`** — same visual language as `PlanApprovalCard` (container styling,
  entrance animation). Renders the question text, quick-pick option buttons (only if
  `options` is non-empty — clicking one calls `onAnswer(option)` immediately), and —
  always shown, even alongside options — a free-text `Input` + send button below them
  (Enter or the button submits, disabled while empty/whitespace). `ChatPanel` wires
  `onAnswer` to send the text through the same path as a normal composer message
  (`addUserMessage` + `sendUserMessage` + `setAgentRunning(true)`) then calls
  `resolveQuestion()` to clear the card locally — there's no dedicated WS frame for the
  answer.
- **`ReasoningBlock.tsx`** — collapsible, collapsed by default (`open` starts false,
  matching the tool-call cards). Header reads "Thinking…" (shimmer) while streaming or
  "Thought process" once done; renders `null` if there's no reasoning text.
- **`ToolCallCard.tsx`** — exports `ToolCallGroup({ calls })`; icon is `Search` if the
  (lowercased) tool name contains `"search"`, else `Wrench`; status icon is a spinning
  `Loader2` (running), `CheckCircle2` (ok), or `XCircle` (error); expands to show
  pretty-printed JSON input and the tool's full output (`output_full`, falling back to
  `output_preview` for legacy records) in a scroll-capped pane.

### 5.5 Curriculum panel components (`components/studio/curriculum/`)

`CurriculumPanel.tsx` dynamically imports **both** `WorkflowView` and `ReaderView` with
`dynamic(..., { ssr: false })` (the spec 03 §5 requirement — Mermaid/xyflow must never
render server-side). It toggles a local `view: "workflow" | "reader"` (default
`"workflow"`); render precedence: no `curriculumId` → `EmptyState`; loading with no data
yet → spinner; error with no data → `EmptyState`; curriculum loaded but no modules yet →
`ActivityFeed` (the pre-content activity mirror described in spec 03); otherwise the
selected view. `CurriculumPanel` owns the reader's selection state as
`activeSelection: { moduleId, sectionId } | null` (lifted here, not local to
`ReaderView`, so a workflow-node click and the reader's own TOC/prev-next controls stay in
sync). `handleSelectModule(moduleId)` resolves that module's first section (lowest
`order`; `sectionId: null` if the module has no sections yet), sets `activeSelection`, and
switches to `"reader"`.

- **`ActivityFeed.tsx`** — a spinning `Sparkles` header showing `phaseLabel`, an
  `AnimatePresence`+`layout`-animated list of the most recent 12 activity items, plus
  skeleton placeholders for the outline-to-come. `humanizeLabel` prefixes "Searching: "
  or "Reading: " based on keyword matching the tool name.
- **`MermaidDiagram.tsx`** — a **raw dynamic ESM `import("mermaid")`** inside a
  `useEffect` (not a Next `dynamic()` call — appropriate since this is a plain library,
  not a React component), re-rendering whenever the `chart` string or `next-themes`'s
  `resolvedTheme` changes. Calls `mermaid.initialize({ startOnLoad: false, theme:
  dark-or-default, securityLevel: "strict", fontFamily: "var(--font-sans-var),
  sans-serif", suppressErrorRendering: true })` and injects the rendered SVG via
  `dangerouslySetInnerHTML` (justified by `securityLevel: "strict"`).
  `suppressErrorRendering: true` stops Mermaid from injecting its own giant error SVG
  into `document.body` on parse failure. On render/parse failure the component degrades
  gracefully instead of showing a destructive error box: it renders the raw `chart`
  source as a plain code block (styled like the loading state) with a small muted note
  that the diagram couldn't render; the actual parser error is only logged via
  `console.warn`, not shown in the UI. Before the SVG is stored in state, a
  `fixLabelContrastForHardcodedFills` post-processing pass walks it on a detached DOM:
  for every `g.node`/`g.cluster` whose shape has an *explicit* fill (agent-authored
  `classDef`/`style`, e.g. `fill:#e0f2e0`), it computes relative luminance and forces
  that group's label text/HTML to near-black or near-white ink via `!important` —
  otherwise mermaid's `dark` theme paints every label a uniform light-gray regardless of
  the node's own background, producing light-on-light text. Theme-default nodes (no
  explicit fill) are left untouched. The successful-render state renders a shared
  `DiagramViewer` subcomponent wrapping the SVG in `react-zoom-pan-pinch`'s
  `TransformWrapper`/`TransformComponent` (statically imported —
  it's a plain React component, not a DOM-touching library like mermaid, so the
  `ssr:false` rule doesn't apply to it) for wheel-zoom (no modifier key, gentle step —
  `0.002` in the lib's `exp(step * |deltaY|)` smooth-zoom formula, ~1.22x per mouse notch)
  and drag-to-pan, plus an absolutely-positioned top-right overlay of icon buttons (zoom
  in/out, reset view, copy source — the last flips to a checkmark for ~1.5s via a `copied`
  state and timeout) styled to match `ui/Button.tsx`'s ghost/icon treatment. In the inline
  (embedded reader) instance only, the overlay cluster is hover-revealed (`opacity-0` ->
  `group-hover:opacity-100`, plus `has-[:focus-visible]:opacity-100` for keyboard users
  tabbing in — deliberately not `focus-within`, which would pin the cluster visible after
  a mouse click on a control since clicks focus the button too, and
  `pointer-coarse:opacity-100` for touch devices where hover never fires) — the
  fullscreen modal instance keeps it always visible. A fifth overlay button
  (`Maximize2`) opens a GitHub-style full-screen popup: a near-full-viewport panel
  hosting a second, fresh `DiagramViewer` instance (so its transform starts at scale 1 —
  no zoom-state syncing) whose expand slot becomes an `X` close control. The modal
  follows `ConfirmDialog.tsx`'s conventions (AnimatePresence fade backdrop, scale/fade
  panel, Escape bound only while open, backdrop click closes with panel clicks stopped)
  but is rendered via `createPortal(..., document.body)` — `MermaidDiagram` sits inside
  Framer-Motion-transformed ancestors, and a CSS transform would make the panel's
  `position: fixed` resolve against that ancestor instead of the viewport — and locks
  body scroll while open (restoring the previous `overflow` value on close).
- **`ReaderView.tsx`** — single-section paging, not an all-sections scroll. A left
  mini-TOC (module/section tree with status icons: `Circle`/`Loader2`/`CheckCircle2` for
  planned/writing/complete) rendered as a sidebar at `lg+`; below `lg` the same tree is
  available from a sticky "Contents" header row that opens an animated dropdown (Framer
  Motion, click-outside-to-close, mirroring the `UserMenu.tsx` pattern). The `lg+` sidebar
  is drag/keyboard-resizable via the same `usePanelResize` hook the studio page's chat
  divider uses (`ic:reader-toc-width`, default 224px, clamped to `[180, min(400, 0.4 *
  innerWidth)]`); its `role="separator"` divider is `hidden lg:block` since the compact
  dropdown TOC below `lg` has no sidebar to resize. Both set the
  active section directly via the controlled `activeSelection`/`onSelectSection` props
  from `CurriculumPanel` — no `scrollIntoView` involved. The content pane renders only the
  active module's active section (module context header + section title/body;
  `"planned"` sections show a "Not written yet" placeholder), flattens all
  module→section pairs in `order` to compute Previous/Next neighbors (labeled with the
  neighbor's title, disabled at the ends, traverses across module boundaries), animates
  the transition with `AnimatePresence` (`mode="wait"`, fade+slide) and resets scroll to
  top on every section change. If `activeSelection` points at a module/section that no
  longer exists after a refetch, it falls back to that module's first entry, then to the
  very first section overall.
- **`SectionContent.tsx`** — custom `ReactMarkdown` `components` overrides: a `code`
  renderer intercepts ` ```mermaid ` fences and renders `<MermaidDiagram>` instead of a
  code block; an `h2` renderer appends an always-rendered, muted "Explain" icon button
  (touch- and keyboard-accessible, `aria-label`ed, brightens on hover/focus) that calls
  `onExplain('Explain "<heading>" in simpler terms')`; an `a` renderer special-cases
  footnote-reference links (`href` starting with
  `#user-content-fn-` or `#fn-`) into small superscript chips, and gives ordinary
  external links `target="_blank" rel="noopener noreferrer"`.
- **`SourcesCard.tsx`** — renders `null` for empty citations; each entry gets a Google
  favicon (`https://www.google.com/s2/favicons?domain={hostname}&sz=32` — an external
  network call with no self-hosted fallback), a numbered badge, and an external-link
  icon.
- **`WorkflowView.tsx`** — `@xyflow/react` canvas. `buildLayout()` places the Start node
  at `x=0` (fixed width `START_NODE_WIDTH = 260`, exported from `nodes/StartNode.tsx` —
  the node has no natural max-width, so without a fixed width a long curriculum title
  widens the card past where module 0 is positioned and the two visibly overlap) and lays
  module nodes out in a **single horizontal row, left to right**, sorted by `order`:
  module `i` sits at `x = START_NODE_WIDTH + H_GAP + i * (NODE_WIDTH + H_GAP)`, all at the
  same `y`, connecting them sequentially with `status` edges (`data.animated = status ===
  "writing"`). Node handles are `Position.Left` (target) / `Position.Right` (source) on
  `ModuleNode`/`StartNode` to match the left-to-right flow. Every node object also sets
  explicit `width`/`height` (`START_NODE_WIDTH`×`START_NODE_HEIGHT` for the Start node,
  `NODE_WIDTH`×`NODE_HEIGHT` for module nodes) matching the rendered card dimensions —
  **this is required for the `MiniMap`**: React Flow's minimap only draws a node's
  rectangle once it knows that node's dimensions, and for custom node types (no default
  width/height) it otherwise waits on `ResizeObserver`-based DOM measurement, which in this
  fully-controlled canvas (`nodes`/`edges` rebuilt via `useMemo`, no `onNodesChange`)
  wasn't resolving — the minimap rendered as a solid mask-colored rectangle with zero
  visible node rects (confirmed via `getComputedStyle` on `.react-flow__minimap-node`:
  before the fix there were no such elements at all; the CSS-custom-property `nodeColor`
  values and the `maskColor` `color-mix()` were both fine in isolation). `fitView({
  padding: 0.25, duration: 300 })` re-runs (via `requestAnimationFrame`) whenever the
  module count changes. The canvas is read-only: `nodesDraggable={false}`,
  `nodesConnectable={false}`, `elementsSelectable={false}`. `colorMode` follows
  `next-themes`. The `MiniMap` sets an explicit `nodeColor` function keyed off each node's
  `status` (via CSS custom properties: `--muted-foreground`/`--accent`/`--success` for
  planned/writing/complete, `--accent` for the Start node) plus
  `nodeStrokeColor`/`nodeBorderRadius` and a `maskColor` built from `color-mix(...
  var(--background) ...)` so it stays legible in both themes. Pan/zoom persists across
  Workflow↔Reader switches even though this component unmounts on every switch (`CurriculumPanel`
  renders one view at a time): `WorkflowInner` reads
  `useCurriculumStore.getState().workflowViewport` once via a `useState` initializer (a plain
  reactive subscription would re-render on every `onMoveEnd` write), passes it as
  `defaultViewport` and sets `fitView={initialViewport ? undefined : true}` so a fresh canvas
  still auto-fits but a restored one doesn't get re-fit over it; the module-count re-fit effect
  skips while a viewport was restored and the module count still equals its mount-time value
  (an idempotent comparison — a consume-once ref failed under StrictMode's dev double-invoke).
  `onMoveEnd` writes the latest `{x, y, zoom}` back to the store on every settle. The store
  clears `workflowViewport` to `null` whenever the loaded curriculum id changes. Note: **`dagre` is listed in
  `package.json` but is not imported or used anywhere in this file** — the layout is
  entirely hand-rolled positional math, not a dagre auto-layout call; this looks like a
  leftover dependency from an earlier layout approach.
- **`edges/StatusEdge.tsx`** — a custom `Edge` using `getSmoothStepPath` (12px border
  radius); dashed + CSS-animated stroke (`xyflow-dash` keyframe in `globals.css`) when
  `data.animated`.
- **`nodes/ModuleNode.tsx`** / **`nodes/StartNode.tsx`** — custom node types keyed off
  `status` (`planned` = dashed border, `writing` = solid accent border + an animated
  progress-shimmer bar, `complete` = success-tinted border) and a gradient Start pill
  respectively.

## 6. `lib/api.ts` conventions

`apiFetch<T>(path, options)` is the single fetch wrapper every API namespace builds on:
- Always sends `credentials: "include"` (required for the `ic_session` cookie).
- Automatically attaches `X-Requested-With: XMLHttpRequest` for any mutating method
  (`POST`/`PUT`/`PATCH`/`DELETE`) — callers never need to remember the CSRF header.
- Supports an `isFormData` flag to pass a `FormData` body through untouched (used by
  resume upload) instead of JSON-stringifying it.
- On a network-level failure (fetch itself throws), raises `ApiError(0, "Network error —
  could not reach the server.", null)`.
- On a **401** response, unless the call opted into `skipAuthRedirect` (used by
  `authApi.me()` and `healthApi.check()` so those two calls can fail without bouncing
  the whole app to `/login`), it does a hard `window.location.href = "/login"` **and**
  throws `ApiError(401, ...)` — callers that do need to observe 401 without redirecting
  must pass that flag explicitly.
- Parses the body as JSON only when the response `content-type` includes
  `application/json`; on a non-OK response it builds the `ApiError` message from the
  body's `detail` (a string, or a FastAPI-validation-style array of `{msg}` objects
  joined by `"; "`) or `message`.

API namespaces (all in `lib/api.ts`): `authApi` (`loginWithGoogle`, `logout`, `me`),
`onboardingApi` (`get`, `update`, `uploadResume`, `synthesize`), `curriculaApi` (`list`,
`get`, `remove`, `plan`), `conversationsApi` (`list`, `create`, `messages`),
`settingsApi` (`get`, `update`), `healthApi` (`check`, with `skipAuthRedirect: true`).

`lib/types.ts` is a hand-maintained TypeScript mirror of every shape in spec 01 —
notably the `ClientEvent` union (`user_message | plan_decision | stop | ping`) and the
full `ServerEvent` union (all 15 event types) match the backend's WS protocol exactly.

`lib/env.ts`'s `readEnv(name, fallback)` exposes exactly three values:
`apiBaseUrl` (`NEXT_PUBLIC_API_BASE_URL`, default `http://localhost:8000`), `wsBaseUrl`
(`NEXT_PUBLIC_WS_BASE_URL`, default `ws://localhost:8000`), `googleClientId`
(`NEXT_PUBLIC_GOOGLE_CLIENT_ID`, default `""`).

`lib/utils.ts`: `cn()` (clsx + tailwind-merge), `timeAgo(iso)`, `initials(name)`, and
`formatElapsed(ms)` — the last of which is currently **exported but never called
anywhere** (see discrepancies below).

## 7. How to add a new page/component consistently

1. **New page**: add a folder+`page.tsx` under `app/`. If it needs auth, wrap it (or its
   layout) with `useAuthGuard({ requireAuth: true, ...})`; if it belongs inside the
   authenticated shell, put it under the `(app)` route group so it inherits
   `AppShell`/the auth+onboarding guard automatically rather than re-implementing it.
2. **New component**: colocate under the most specific existing folder
   (`components/studio/chat/`, `components/studio/curriculum/`, `components/dashboard/`,
   `components/onboarding/`, `components/settings/`, or `components/ui/` for a generic
   primitive). Use `forwardRef` + the shared `cn()` helper + semantic Tailwind tokens
   (never hardcode a hex color — use `bg-card`, `text-muted-foreground`, etc. so both
   themes stay correct for free). Match the existing hand-rolled primitive style in
   `components/ui/` (no Radix/shadcn dependency to reach for).
3. **New WS event type**: add it to both the backend event dict (see
   [agent-system.md](agent-system.md) / `backend/app/ws/chat.py`) and the `ServerEvent`
   union in `lib/types.ts`, then add a case to the dispatch table in
   `hooks/useChatSocket.ts` that calls a new or existing Zustand action.
4. **New store state**: prefer extending `useChatStore`/`useCurriculumStore` if the data
   is chat- or curriculum-scoped; only add a new store for a genuinely separate concern
   (mirroring `useAuthStore`'s scope).
5. **Any component touching Mermaid or `@xyflow/react`**: must be loaded with
   `dynamic(..., { ssr: false })` (component-level) or a runtime `import(...)` inside an
   effect (library-level, as `MermaidDiagram.tsx` does) — never a top-level static
   import, or the build will try to server-render a browser-only library.
6. **Verify**: `npm run build` must pass with zero TypeScript errors before considering
   any change done (per the root and frontend `CLAUDE.md`).

## Notable behaviors beyond `docs/specs/03-frontend-spec.md`

1. **`CurriculumGrid` polls `curriculaApi.list()` every 8 seconds** on the dashboard so
   in-progress curricula update live there — an intentional mechanism separate from the
   WS-driven updates used inside Studio (the dashboard has no WS connection).
2. **Tool-call timing**: `tool_call_result`'s `elapsed_ms` is stored on the live
   `ToolCallRecord` (optional field — absent for hydrated history, which doesn't persist
   it) and shown in `ToolCallCard` via `formatElapsed()` once a call finishes.
3. **"Explain this"** is an always-rendered muted icon button next to each section `<h2>`
   in `SectionContent.tsx` (keyboard- and touch-accessible; brightens on hover/focus),
   which prefills the chat composer via `onExplain(...)`.
4. **Reader TOC responsiveness**: the sidebar TOC renders at `lg+`; below `lg`,
   `ReaderView.tsx` shows a sticky "Contents" header row that opens an animated dropdown
   with the same module/section tree. Both set the active section directly (single-section
   paging) rather than scrolling to it.
5. **Code-block syntax highlighting** is a hand-written dual-theme hljs palette at the
   end of `globals.css` (GitHub-light colors under `:root`, GitHub-dark under `.dark`)
   rather than an imported highlight.js stylesheet.
6. **Sidebar's "New curriculum" button never hits the API.** `Sidebar.tsx`'s
   `handleNewCurriculum` just navigates to `/dashboard` (closing the mobile drawer via
   `onNavigate?.()` first) — it does not call `conversationsApi.create(...)`. The
   dashboard's `PromptBox` is the only place a conversation/curriculum doc gets created,
   avoiding empty junk conversations from an unused sidebar click.
7. **`role: "system"` messages are never rendered.** The backend persists internal
   bookkeeping messages (plan-approval records) with `role: "system"`.
   `useChatStore.hydrateHistory` filters them out before they ever enter the `messages`
   array — this is the single boundary where filtering happens, so
   `ChatPanel`/`MessageBubble` never need to special-case the role.

## Related documents

- [backend.md](backend.md) — the REST/WS surface this frontend consumes.
- [agent-system.md](agent-system.md) — what generates the events rendered here.
- `frontend/CLAUDE.md` — terse scoped conventions for AI-assisted edits.
