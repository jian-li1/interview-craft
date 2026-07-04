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
  time, delete w/ confirm). Empty state illustration.
- **Settings**: tabs — Profile (link/embed onboarding edit), Preferences (LLM provider,
  search provider dropdowns — "server default" option), Appearance (theme), Account (email, logout).

## 3. Studio (the core screen)

Split layout: chat panel left (~40%, min 380px), curriculum panel right (resizable divider
nice-to-have; fixed split acceptable). Mobile: tabbed switcher.

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
  is running (sends `stop`), disabled states, reconnect logic with exponential backoff and
  "reconnecting…" toast.
- History hydration: on load fetch GET /api/conversations/{id}/messages and render
  (including persisted tool calls + reasoning as collapsed blocks).

### Curriculum panel
Two views, toggle: **Workflow** and **Reader**.
- **Workflow view (n8n-style)**: @xyflow/react canvas. Custom nodes: a Start node
  (curriculum title + emoji), then module nodes laid out sequentially (vertical or
  serpentine) connected by animated edges; each module node shows order badge, title,
  status (planned=dashed border, writing=pulsing accent, complete=filled check), section
  count, estimated minutes; clicking a module expands/navigates to Reader view at that
  module. Section child-nodes fan out from a module (or listed inside the node card).
  Auto-fit view; smooth node status animations as `curriculum_updated` events arrive.
- **Reader view**: left mini-TOC (modules→sections, status icons) + content area rendering
  section `content_markdown`: react-markdown + remark-gfm + rehype-highlight; **Mermaid**
  code fences rendered as diagrams (client component, re-render on theme change);
  citations: `[^n]` footnotes rendered, plus a Sources card at the section end (favicon,
  title, url, external-link). "Explain this" affordance: selecting a section header shows
  a button that prefills the chat composer with "Explain <section> in simpler terms".
- Panel live-updates: on `curriculum_updated` refetch curriculum (SWR-style with the api
  client) and animate new/changed nodes & sections.
- While researching/planning (no content yet): show an animated activity feed panel
  (recent tool activity mirrored: "Searching: …", "Reading: example.com") + skeletons.

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
