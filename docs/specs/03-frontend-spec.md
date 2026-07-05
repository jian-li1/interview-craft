# InterviewCraft — Frontend UX & Implementation Spec

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
  preparing for?") with example prompt chips — submitting creates a conversation
  (POST /api/conversations with the prompt) and routes to /studio/[id]; grid of curriculum
  cards (emoji, title, status badge, progress bar when generating, module count, updated
  time, delete w/ confirm). Empty state illustration. The dashboard's prompt box is the
  *only* way to create a curriculum — the sidebar's "New curriculum" button never calls the
  API; it just navigates to /dashboard (see §2 sidebar note below).
- **Settings**: tabs — Profile (link/embed onboarding edit), Preferences (LLM provider,
  search provider dropdowns — "server default" option), Appearance (theme), Account (email, logout).

## 3. Studio (the core screen)

Split layout: chat panel left, curriculum panel right, separated by a drag-resizable
divider (pointer-drag + ArrowLeft/ArrowRight keyboard support on a focusable
`role="separator"`). Chat column defaults to 480px, clamped to [340px, min(720px, 60vw)],
persisted across visits in `localStorage` under `ic:studio-chat-width`. Mobile: tabbed
switcher (unaffected by the divider).

### Chat panel (Claude/ChatGPT-grade)
- Message list with user/assistant bubbles, markdown rendering in assistant messages.
- **Streaming**: connect WS on mount; render `text_delta` token-by-token with a blinking
  caret; auto-scroll with "scroll to bottom" pill when user scrolled up.
- **Reasoning chain**: `reasoning_delta` streams into a collapsible "Thinking…" block
  (shimmer label while streaming, collapses to a subtle expandable row when done).
- **Tool calls**: each renders as a compact card: icon + tool name + status spinner →
  check/error; expandable to show formatted JSON input and output preview. Group
  consecutive tool cards. This is the agent-transparency UI — make it polished.
- **Phase banner**: sticky chip showing current phase from `phase_change`
  (Researching → Planning → Awaiting your approval → Writing → Ready) with animated icon.
- **Plan approval card (HITL)**: on `plan_proposed`, render a rich card: outline preview,
  task checklist, textarea for change requests, [Approve & build] / [Request changes]
  buttons → send `plan_decision`. Disable input while awaiting.
- Composer: auto-growing textarea, Enter=send Shift+Enter=newline, stop button while agent
  is running (sends `stop`, which aborts promptly — see spec 01 §7 — rather than waiting
  for the current LLM stream chunk or tool call to finish on its own), disabled states,
  reconnect logic with exponential backoff and "reconnecting…" toast.
- History hydration: on load fetch GET /api/conversations/{id}/messages and render
  (including persisted tool calls + reasoning as collapsed blocks). Messages with
  `role: "system"` (internal bookkeeping — auto-continue nudges, plan-approval records) are
  filtered out at the history-load boundary and never rendered in the chat UI.

### Curriculum panel
Two views, toggle: **Workflow** and **Reader**.
- **Workflow view (n8n-style)**: @xyflow/react canvas, linear left-to-right layout. Custom
  nodes: a Start node (curriculum title + emoji) at the far left with a **fixed width**
  (`START_NODE_WIDTH`, exported from `nodes/StartNode.tsx`) so long curriculum titles
  truncate instead of widening the card and overlapping the first module, then module
  nodes sorted by `order` laid out as a single horizontal row to its right (one node per
  step, equal spacing), connected by animated edges that flow left→right; node handles are
  `Position.Left` (target) / `Position.Right` (source) to match. Each module node shows
  order badge, title, status (planned=dashed border, writing=pulsing accent, complete=filled
  check), section count, estimated minutes. Clicking a module node resolves that module's
  first section (lowest `order`) and switches to the Reader view focused there (module with
  no sections yet: Reader still switches to that module, showing its "not written" state).
  Auto-fit view; smooth node status animations as `curriculum_updated` events arrive. Every
  node object also carries explicit `width`/`height` (matching its rendered card size) so
  the `MiniMap` can draw node rectangles without depending on DOM measurement; the minimap
  gives each node an explicit `nodeColor` keyed off status (planned=muted, writing=accent,
  complete=success) plus a theme-aware `maskColor` (CSS custom properties, not hardcoded
  hex) so it renders visibly in both light and dark themes.
- **Reader view**: left mini-TOC (modules→sections, status icons) + a single-section content
  pane — only the active module's active section is rendered at a time (not a long
  all-sections scroll). Selecting a TOC entry (desktop nav or mobile dropdown) sets the
  active section directly rather than scrolling to it. Content: module context header
  (module title/order/status) above the section title + body, rendered via react-markdown +
  remark-gfm + rehype-highlight; **Mermaid** code fences rendered as diagrams (client
  component, re-render on theme change); citations: `[^n]` footnotes rendered, plus a
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
- `lib/ws.ts`: ChatSocket class — connect/reconnect/backoff, typed event handlers,
  send helpers, ping keepalive.
- `lib/types.ts`: TypeScript mirrors of every contract shape from spec 01.
- Zustand stores: `useAuthStore` (user, loading), `useChatStore` (messages, streaming
  buffers keyed by message_id, phase, plan, agent running flag), `useCurriculumStore`
  (curriculum tree, refetch actions).
- All components typed strictly; `npm run build` must pass with zero type errors.

## 5. Quality bar

- Responsive down to 375px. Keyboard accessible (focus rings, aria labels on icon buttons).
- Empty/loading/error states everywhere. Toasts (simple custom or sonner) for errors.
- No hydration warnings; mermaid/xyflow rendered client-side only (dynamic import, ssr:false).
