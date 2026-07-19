# InterviewBlueprint — Frontend UX & Implementation Spec

Next.js 15 App Router + TypeScript + Tailwind v4. Conform to API/WS contracts in spec 01.

## 1. Design language

- Modern, clean SaaS aesthetic (think Linear/Claude.ai): generous whitespace, soft borders,
  subtle shadows, rounded-xl cards, 1 accent color (indigo/violet gradient family).
- Light + dark themes via `next-themes` (class strategy), theme toggle in navbar and settings.
  Define semantic CSS variables (--background, --foreground, --card, --accent, ...) consumed
  by Tailwind theme tokens so both themes stay consistent.
- Smooth animations with Framer Motion: page/section fade-slide-ins, staggered lists,
  animated status transitions, skeleton shimmer loaders. Keep durations 150–350ms.
- Icons: lucide-react. Font: Inter (or Geist) via next/font.

## 2. Pages (App Router)

```
/                     Landing (public)
/login                Login/signup (public)
/onboarding           Onboarding wizard (auth; forced when !onboarding_completed)
/dashboard            Home: curricula gallery + "new curriculum" entry
/studio/[conversationId]   THE WORKSPACE: chat left / curriculum right
/settings             Profile, AI provider prefs, theme, account
```

Route group `(app)` with shared authenticated layout (sidebar nav: Dashboard, New
Curriculum, Settings; user avatar menu with logout). Auth guard: fetch `/api/auth/me` in a
client provider; redirect to /login on 401; redirect to /onboarding when profile incomplete.
The sidebar's "New curriculum" button does **not** call any API — it never creates a
conversation doc — it simply navigates to /dashboard, where the PromptBox is the sole entry
point for starting a curriculum (avoids junk empty-conversation documents).
On desktop, the sidebar is collapsible: a `PanelLeftClose`/`PanelLeftOpen` toggle button in
the header (left of the theme/user controls) animates the sidebar width between 256px and 0
(Framer Motion tween, 200ms); state defaults open and persists in `localStorage` under
`ic:sidebar-open`, synced client-side post-mount to avoid an SSR hydration mismatch. Mobile
drawer behavior is unchanged (slide-in overlay, unaffected by the desktop collapse state).

- **Landing**: hero (headline, subheadline, CTA → /login), animated product mock (stylized
  chat+workflow illustration built with divs, no images), features grid (Deep Research,
  Human-in-the-loop Planning, Visual Curricula, Cited Sources), "how it works" 4-step
  section, footer. Fully responsive, dark-mode aware, tasteful gradient accents.
- **Login**: card with Google Sign-In button (Google Identity Services script,
  `renderButton`), on credential → POST /api/auth/google → route to /onboarding or /dashboard.
- **Onboarding wizard** (4 steps, progress indicator, framer-motion step transitions):
  1. Bio & background (textareas), 2. Target roles (chip input), experience level (select),
  timeline, 3. Skills (chips), goals, learning style, resume upload (drag-drop, pdf/docx/txt,
  shows extracted preview), 4. Review → "Generate my profile" → calls PUT /api/onboarding
  then POST /synthesize; shows the synthesized profile with an editable/regenerate step;
  finish → /dashboard. Revisitable from settings ("Edit background").
- **Dashboard**: greeting with user name; prominent prompt box ("What interview are you
  preparing for?") with a column layout — textarea on top, then a bottom row with model
  (`Bot` icon) / search-provider (`Globe` icon) `ChipSelect` chips on the left, a flexible
  spacer, and the send button on the right, then a row of example prompt chips below the
  box. The model/search-provider chip options come from `GET /api/models` (fetched once
  on mount via `modelsApi.get()` — a plain REST call, since these options aren't part of
  the dashboard WS's event protocol; the studio composer instead hydrates from
  `session_ready`); options default-select to the response's
  `default_model`/`default_search_provider` and are rendered only once their list is
  non-empty (a fetch failure just leaves the chips off, never blocking the box).
  Submitting creates a conversation (POST /api/conversations with the prompt plus any
  chip selection) and routes to /studio/[id]; grid of curriculum cards (emoji, title,
  subtitle showing the agent-written `description` — falling back to `user_prompt` for
  legacy curricula or before a plan is first proposed, `line-clamp-3` — status badge,
  progress bar when generating, module count, updated time, favorite star, delete w/
  confirm). Empty state illustration. The dashboard's prompt box is the *only* way to
  create a curriculum — the sidebar's "New curriculum" button never calls the API; it
  just navigates to /dashboard (see §2 sidebar note below). The grid loads via
  `curriculaApi.list()` on mount, then stays live via a `DashboardSocket`
  (`/ws/dashboard`, see spec 01 §7b) opened in the same effect: `curriculum_updated`
  upserts the changed card (by id, preserving grid position; a not-yet-seen id is
  prepended) and `curriculum_deleted` removes it — no more polling. On reconnect after a
  dropped connection the full list is refetched once, to catch any changes missed while
  offline.
  - **Favorites + filter/sort**: each card shows a `lucide Star` button in its top row
    (before the delete button). Favorited: always visible, filled yellow
    (`fill-amber-400 text-amber-400`, same in both themes). Not favorited: hover-reveal
    like the trash button, muted color, hover turns amber. Clicking calls
    `curriculaApi.update(id, {favorite})` (PATCH `/api/curricula/{id}`) optimistically —
    the grid flips the card's `favorite` locally first, reverting + toasting on error;
    the dashboard WS's own `curriculum_updated` echo is a harmless no-op replace after.
    The "Your curricula" header row (owned by `dashboard/page.tsx`, not the grid) adds two
    controls to the right: an "Updated" ghost button with an `ArrowDown`/`ArrowUp` icon
    that flips sort direction on `updated_at`, and an All curricula/Favorites `Tabs`
    segmented control (same primitive as the studio's Workflow/Reader toggle). Both are
    plain local page state (`filter`, `sortDesc`) passed down as props;
    `CurriculumGrid` applies them to a render-time copy of its fetched list (the
    underlying state keeps server order, so the WS upsert logic never fights a
    client-side sort). Filtering to Favorites with none starred renders an `EmptyState`
    (icon `Star`, "No favorites yet").
- **Settings**: tabs — Profile (link/embed onboarding edit), Appearance (theme), Account
  (email, logout). No more Preferences tab — LLM model / search provider selection moved
  to the chat composer's chips (per-conversation, see §3 below), not a settings page.

## 3. Studio (the core screen)

Split layout: chat panel left, curriculum panel right, separated by a drag-resizable
divider (pointer-drag + ArrowLeft/ArrowRight keyboard support on a focusable
`role="separator"`). Chat column defaults to 480px, clamped to [340px, min(720px, 60vw)],
persisted across visits in `localStorage` under `ic:studio-chat-width`. Mobile: tabbed
switcher (unaffected by the divider). The curriculum panel header also has a full-screen
"focus mode" toggle (also exits on Escape) that hides the app header, nav sidebar, and
chat column — the chat column stays mounted, just CSS-hidden, so its scroll/draft state
survives; state lives on `useCurriculumStore.focusMode` and is force-cleared when the
studio page unmounts. The header's title also gets a hover-revealed `lucide Pencil`
button (same reveal pattern as the dashboard card's delete/star buttons) that opens
`RenameCurriculumDialog` — a `ConfirmDialog`-style modal (same backdrop/Escape/animation
conventions) with a Name input and a Description textarea (both pre-filled, capped at
100/500 chars client-side to match the backend). Save sends only the changed field(s) via
`curriculaApi.update` (PATCH `/api/curricula/{id}`) and applies the response into
`useCurriculumStore` via the `applyMeta` action (shallow-merges title/description into
the loaded curriculum without a full refetch).

### Chat panel (Claude/ChatGPT-grade)
- Message list with user/assistant bubbles, markdown rendering in assistant messages.
- **Streaming**: connect WS on mount; render `text_delta` token-by-token with a blinking
  caret; auto-scroll with "scroll to bottom" pill when user scrolled up.
- **Reasoning chain**: `reasoning_delta` streams into a collapsible "Thinking…" block
  (collapsed by default, like tool-call cards; shimmering header while streaming, "Thought
  process" when done; expandable on click).
- **Tool calls**: each renders as a compact card: icon + tool name + status spinner →
  check/error; expandable to show formatted JSON input and the tool's full output. Group
  consecutive tool cards. This is the agent-transparency UI — make it polished.
- **Run elapsed time**: small muted `Clock + duration` line under assistant messages showing
  how long the whole agentic run took (all ReAct iterations, from user send to `agent_done`).
  While a run is in flight it ticks live (1s, client-side approximation) under the newest
  assistant message; the frozen total is the server-measured `elapsed_ms` carried on
  `agent_done` — authoritative, persisted as `run_elapsed_ms` on the run's final assistant
  message and returned in history, overwriting any local estimate (a non-recoverable
  `error` with no `agent_done` still falls back to the local `runStartedAt` diff). Format
  `18s` / `4m 25s` / `1h 4m`. `message_end` no longer clears the running state — it fires
  between ReAct iterations mid-run; `agent_done` (now emitted on every terminal path,
  including LLM-stream failures and internal errors) is the sole authority for that. The
  timestamp-derivation fallback (deriving duration from message timestamps: user/system
  messages written at run start, each assistant message at its iteration's end) only
  applies to conversations predating the `run_elapsed_ms` field.
- **Phase banner**: sticky chip showing current phase from `phase_change`
  (Researching → Planning → Awaiting your approval → Writing → Ready) with animated icon.
- **Plan approval card (HITL)**: on `plan_proposed`, render a rich card: outline preview,
  task checklist, textarea for change requests, [Approve & build] / [Request changes]
  buttons → send `plan_decision`. Disable input while awaiting.
- **Question card (HITL)**: on `user_input_requested`, render an inline card (same visual
  language as the plan approval card): question text, quick-pick option buttons if
  `options` is non-empty (clicking one submits that option's text), and — always shown,
  even alongside options — a free-text input below them for a custom answer (Enter or a
  send button submits; disabled while empty/whitespace). Both answer paths send the chosen
  text as an ordinary `user_message` frame (there is no dedicated "answer" frame type) and
  then clear the card locally. Composer is disabled while the card is showing, mirroring
  the plan card. The card is restored on reconnect if the state doc's `pending_user_input`
  is still set (see spec 01 §7).
- Composer: auto-growing textarea, Enter=send Shift+Enter=newline, stop button while agent
  is running (sends `stop`, which aborts promptly — see spec 01 §7 — rather than waiting
  for the current LLM stream chunk or tool call to finish on its own), disabled states,
  reconnect logic with exponential backoff and "reconnecting…" toast.
- **Model / search-provider chips**: inside the SAME outlined input box as the textarea
  (not a separate row below it) — the box is a column: textarea on top, then a bottom row
  (`ChipSelect`, `components/ui/ChipSelect.tsx` — a shared primitive also used by the
  dashboard prompt box) with the two chips on the left, a flexible spacer, and the
  send/stop button on the right. Each chip is a compact pill (icon + current value +
  chevron) — `Bot` for the model chip, `Globe` for the search-provider chip (friendly
  labels via the shared `SEARCH_PROVIDER_LABELS` map exported alongside `ChipSelect`:
  duckduckgo → "DuckDuckGo", google → "Google", tavily → "Tavily") — that opens an
  UPWARD-anchored popover (the composer sits at the bottom of the chat panel, so a
  downward popover would be clipped) listing options with a check mark on the current
  selection and, for the model chip, a muted `openai`/`gemini` badge per option; closes
  on outside click, Escape, or picking an option. The chip trigger hovers to
  `accent-soft` (not the vivid `--accent` fill, which reads unreadable against the
  chip's muted text in both themes) and popover option rows hover the same way. Options/
  current values come from `useChatStore`'s `availableModels`/`selectedModel`/
  `searchProviders`/`selectedSearchProvider`, hydrated from the `session_ready` WS event
  (spec 01 §7) via `setModelOptions`; picking an option calls `setSelectedModel`/
  `setSelectedSearchProvider` (local-only — no WS frame is sent on selection). The
  current selections are then attached to every subsequent `user_message`/
  `plan_decision`/`compact` frame the composer sends. Both chips are disabled (reduced
  opacity, non-interactive) whenever the composer itself is disabled.
- **"Current section as context" chip**: a third chip, rendered immediately after the
  model/search-provider chips (same pill styling, `h-7 max-w-[160px]` etc. — a plain
  toggle button, not a `ChipSelect` popover). Visible only when ALL of: the curriculum
  panel is in Reader view (`useCurriculumStore`'s `view === "reader"`), the Reader's
  active section (resolved via `lib/reader.ts`'s `flattenCurriculum`/
  `resolveActiveIndex` — the same logic ReaderView itself uses, so the chip always names
  exactly what's on screen) is non-null and not `status: "planned"`, and the agent
  `phase` is one of `writing`/`review`/`ready`/`refinement` (derived in `ChatPanel`, not
  `Composer`, which just renders whatever it's given). Label:
  `` `${module.order + 1}.${section.order + 1} ${section.title}` `` (1-based display of
  the 0-based `order` fields), truncated like the other chips. Toggle states, both
  sticky for the session (a single boolean, default **included**, never auto-resets when
  the underlying section changes — only user clicks flip it):
  - **Included** (default): `FileText` icon + label, normal chip styling.
  - **Excluded**: `EyeOff` icon + label, `opacity-50` — dimmed but still fully clickable
    to toggle back (not disabled).
  `aria-pressed` reflects the toggle state; `aria-label`/`title` name the action/current
  state. When hidden (wrong view/phase/no section/still-planned), nothing about it is
  ever sent — not even an "excluded" marker. When visible AND included, the next
  `user_message` frame's `send` call attaches
  `section_context: {module_id, section_id}` (see spec 01 §7); the plan-decision and
  HITL-question-answer send paths never attach it, since neither is "the user's own next
  message about what they're reading." Respects the composer's `disabled` prop like the
  other two chips. When the backend validates the snapshot, `ChatPanel`'s optimistic
  user bubble (and, after a reload, the replayed history message via the persisted
  `section_context` field) renders a small `FileText` chip above the message text inside
  the bubble — same `${module}.${section} ${title}` label, subdued translucent
  `primary-foreground/10`-`/15` styling so it reads quieter than the message itself on
  the filled `bg-primary` bubble in both themes (`MessageBubble.tsx`). Chip sizing: the
  wrapper's `w-0` + `min-w-full` pair zeroes the chip's intrinsic-width contribution (so
  its nowrap label can never inflate the bubble past the panel at narrow chat-column
  widths) and then stretches it to the bubble width the message text resolved — the
  label shows in full whenever the bubble is wide enough and truncates only at the
  bubble's far edge.
- History hydration: on load fetch GET /api/conversations/{id}/messages and render
  (including persisted tool calls + reasoning as collapsed blocks). Messages with
  `role: "system"` (internal bookkeeping — auto-continue nudges, plan-approval records) are
  filtered out at the history-load boundary and never rendered in the chat UI.
- **Compaction chip**: a full-width divider-style chip (`hairline — pill — hairline`)
  interleaved into the transcript, anchored to the message it ran after. `compaction_start`
  renders it in a "running" state (spinner + "Auto-compacting conversation…"); while a
  compaction is running the composer is disabled with an "Auto-compacting conversation…"
  placeholder. `compaction` resolves the chip in place to "done" (icon + "Auto-compacted"
  + a `48.2k → 12.1k tokens` detail, omitted when the before-count is 0/legacy) — clicking
  a done chip expands an AnimatePresence panel showing the FULL rolling `summary` text in
  a scroll-capped (max-h-60) pane styled like the reasoning block's dropdown, with the
  "Summary of compacted history" caption pinned outside the scrolling region. Survives
  page reloads: the WS reconnect snapshot (spec 01 §7) replays a `compaction` event from
  the conversation doc's persisted checkpoint, which the store appends directly in the
  "done" state (deduped on the `compacted_through` fold-point id).
- **Context-usage warning card**: visually attached to the top of the composer's input box
  (shares its rounded corners so the two read as one unit) once `context_usage`'s
  `tokens/limit` crosses 70% — warns "Context X% full" and that auto-compaction fires at
  `threshold` (80%), with a "Compact now" button that sends the `compact` WS frame;
  disabled while the agent is running or a compaction is already in flight (swaps its
  label to "Compacting…").

### Curriculum panel
Two views, toggle: **Workflow** and **Reader**.
- **Workflow view (n8n-style)**: @xyflow/react canvas, linear left-to-right layout. Custom
  nodes: a Start node (curriculum title + emoji) at the far left with a **fixed width**
  (`START_NODE_WIDTH`, exported from `nodes/StartNode.tsx`) so long curriculum titles
  truncate instead of widening the card and overlapping the first module, then module
  nodes sorted by `order` laid out as a single horizontal row to its right (one node per
  step, equal spacing), connected by animated edges that flow left→right; node handles are
  `Position.Left` (target) / `Position.Right` (source) to match. Each module node is
  `280px` wide (`NODE_WIDTH`) and shows order badge, title (`line-clamp-2`), the
  agent-written `description` when non-empty (shown under the title, `line-clamp-3`),
  status (planned=dashed border, writing=pulsing accent, complete=filled
  check), section count, estimated minutes. Clicking a module node resolves that module's
  first section (lowest `order`) and switches to the Reader view focused there (module with
  no sections yet: Reader still switches to that module, showing its "not written" state).
  Auto-fit view; smooth node status animations as `curriculum_updated` events arrive. The
  canvas's pan/zoom persists across Workflow↔Reader switches (the view unmounts on switch):
  saved to `useCurriculumStore.workflowViewport` on move-end, restored via `defaultViewport`
  on remount, with the auto-fit-on-mount skipped whenever a saved viewport is being restored;
  cleared to `null` when the loaded curriculum changes (a saved camera from one curriculum
  doesn't apply to another). Every
  node object also carries explicit `width`/`height` (matching its rendered card size) so
  the `MiniMap` can draw node rectangles without depending on DOM measurement; the minimap
  gives each node an explicit `nodeColor` keyed off status (planned=muted, writing=accent,
  complete=success) plus a theme-aware `maskColor` (CSS custom properties, not hardcoded
  hex) so it renders visibly in both light and dark themes.
- **Reader view**: left mini-TOC (modules→sections, status icons) + a single-section content
  pane — only the active module's active section is rendered at a time (not a long
  all-sections scroll). Selecting a TOC entry (desktop nav or mobile dropdown) sets the
  active section directly rather than scrolling to it. The lg+ mini-TOC is drag/keyboard-
  resizable (same separator pattern as the studio page's chat divider), clamped to
  [180px, min(400px, 40vw)] and persisted under `ic:reader-toc-width`. Content: module
  context header (module title/order/status) above the section title + body, rendered via
  react-markdown + remark-gfm + rehype-highlight; **Mermaid** code fences rendered as
  diagrams (client component, re-render on theme change) — an interactive viewer
  (react-zoom-pan-pinch) with wheel-zoom/drag-pan (gentle step, ~1.22x per mouse notch)
  plus a zoom-in/zoom-out/reset/copy-source/full-screen overlay control cluster that's
  hover-revealed in the inline view (always visible in the full-screen modal), a
  near-full-viewport full-screen popup modal (rendered through a
  portal to `document.body` so transformed ancestors can't clip it; Escape and backdrop
  click close it) hosting the same shared viewer, and a post-render contrast pass that
  recolors labels sitting on hardcoded
  light/dark `classDef`/`style` fills so agent-generated diagrams stay legible in dark
  mode; citations: `[^n]` footnotes rendered, plus a
  Sources card at the section end (favicon, title, url, external-link). `"planned"` sections
  show a "Not written yet" placeholder. Previous/Next buttons at the bottom of the content
  area traverse the flattened section order across module boundaries (disabled at the ends,
  labeled with the neighboring section's title); section transitions animate via
  AnimatePresence and reset scroll to top. If the active selection is deleted/absent after a
  refetch, falls back to the first section. "Explain this" affordance: selecting a section
  header shows a button that prefills the chat composer with "Explain <section> in simpler
  terms".
- Panel live-updates: on `curriculum_updated` refetch curriculum (SWR-style with the api
  client) and animate new/changed nodes & sections.
- While researching/planning (no content yet): show an animated activity feed panel with
  the full live tool-activity list (friendly per-tool labels, e.g. "Searching the web" /
  "Reading a web page", each row an expandable disclosure showing raw input/output;
  scrolls independently, capped to half the viewport height) and a curriculum outline
  card once a plan has been proposed (falls back to skeleton placeholders only before any
  plan exists).

## 4. State & lib

- `lib/api.ts`: typed fetch wrapper (credentials: "include", X-Requested-With header,
  JSON errors → typed ApiError; 401 → redirect to /login).
- `lib/ws.ts`: a shared `SocketBase` (connect/reconnect/backoff, typed event handlers,
  ping keepalive) subclassed by `ChatSocket` (`/ws/chat/{conversationId}`, plus its
  send helpers) and `DashboardSocket` (`/ws/dashboard`, read-only beyond the inherited
  ping) — see §2's Dashboard bullet and spec 01 §7b for the dashboard grid's live-update
  protocol.
- `lib/types.ts`: TypeScript mirrors of every contract shape from spec 01.
- `lib/reader.ts`: pure (no DOM/ssr:false coupling) `flattenCurriculum`/
  `resolveActiveIndex` helpers shared by `ReaderView` and `ChatPanel`'s section-context
  chip, so both agree on exactly which (module, section) is "current."
- Zustand stores: `useAuthStore` (user, loading), `useChatStore` (messages, streaming
  buffers keyed by message_id, phase, plan, agent running flag), `useCurriculumStore`
  (curriculum tree, refetch actions, plus the curriculum panel's `view`
  (Workflow/Reader) and `activeSelection` (module/section) — lifted out of
  `CurriculumPanel` local state so the composer's section-context chip can read them).
- All components typed strictly; `npm run build` must pass with zero type errors.

## 5. Quality bar

- Responsive down to 375px. Keyboard accessible (focus rings, aria labels on icon buttons).
- Empty/loading/error states everywhere. Toasts (simple custom or sonner) for errors.
- No hydration warnings; mermaid/xyflow rendered client-side only (dynamic import, ssr:false).
- Mermaid parse failures degrade gracefully — the source renders as a plain code block
  with a note (no raw parser error box), and Mermaid's own DOM error injection is
  suppressed (`suppressErrorRendering: true`).
