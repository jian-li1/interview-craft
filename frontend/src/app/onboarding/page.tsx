"use client";

import { useEffect, useId, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, ArrowRight, Loader2, Sparkles, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { WizardProgress } from "@/components/onboarding/WizardProgress";
import { ResumeDropzone } from "@/components/onboarding/ResumeDropzone";
import { ChipInput } from "@/components/ui/ChipInput";
import { Input, Textarea } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { onboardingApi, ApiError } from "@/lib/api";
import type { ExperienceLevel, ProfileIn } from "@/lib/types";
import { useAuthGuard } from "@/components/auth/useAuthGuard";
import { useAuth } from "@/components/auth/AuthProvider";

const EXPERIENCE_OPTIONS: { value: ExperienceLevel; label: string }[] = [
  { value: "student", label: "Student" },
  { value: "entry", label: "Entry level" },
  { value: "mid", label: "Mid level" },
  { value: "senior", label: "Senior" },
  { value: "career_change", label: "Career change" },
];

const emptyProfile: ProfileIn = {
  bio: "",
  background: "",
  target_roles: [],
  experience_level: "entry",
  skills: [],
  goals: "",
  learning_style: "",
  timeline: "",
};

const TOTAL_STEPS = 4;

/**
 * `/onboarding` — post-signup profile wizard, shown once to new users after
 * their first Google sign-in (before they reach `/dashboard`).
 *
 * Guarded with `useAuthGuard({ requireAuth: true })` only (not
 * `requireOnboarding`, since the whole point of this page is to let
 * not-yet-onboarded users in) and lives outside the `(app)` route group —
 * see `frontend/CLAUDE.md`'s structure map: `/`, `/login`, and `/onboarding`
 * are public/semi-public pages that sit alongside, not inside, the
 * authenticated shell.
 *
 * State machine: a 4-step linear wizard driven by `step` (1-indexed) plus
 * `direction` (±1, purely for the slide-in/out animation direction in
 * `AnimatePresence`). `goTo(next)` is the only step transition entry point;
 * it derives `direction` from whether `next` is ahead of or behind the
 * current step. Steps:
 *   1. `StepBackground` — bio + education/work background (free text).
 *   2. `StepRoles` — target roles (chip input), experience level, timeline.
 *   3. `StepSkills` — skills (chip input), goals, learning style, resume
 *      upload (`ResumeDropzone`, which extracts resume text server-side).
 *   4. `StepReview` — read-only summary of steps 1-3, plus an explicit
 *      "Generate my profile" action that calls the backend to synthesize a
 *      free-text profile summary (`synthesizedProfile`) the agent will use
 *      as long-term memory; editable before finishing.
 * `validateStep()` gates forward navigation per step (steps 1-3 only; step 4
 * has no free-text validation, it's gated by `!synthesizedProfile` instead
 * disabling the Finish button until a profile has been generated).
 * `handleNext` persists the in-progress profile via `onboardingApi.update`
 * before advancing, so a page refresh mid-wizard doesn't lose progress (the
 * mount effect below re-fetches any existing partial profile).
 * `handleFinish` marks `onboarding_completed: true`, refreshes the cached
 * auth user (so `useAuthGuard`'s `requireOnboarding` checks elsewhere in the
 * app see the update immediately), and redirects to `/dashboard`.
 *
 * Note: this page does not contain a "New curriculum" button — that action
 * lives in `components/layout/Sidebar.tsx` within the authenticated shell,
 * not here.
 */
export default function OnboardingPage() {
  const { ready } = useAuthGuard({ requireAuth: true });
  const { refresh } = useAuth();
  const router = useRouter();

  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [synthesizing, setSynthesizing] = useState(false);
  const [profile, setProfile] = useState<ProfileIn>(emptyProfile);
  const [resumeFilename, setResumeFilename] = useState<string | null>(null);
  const [resumeText, setResumeText] = useState<string | null>(null);
  const [synthesizedProfile, setSynthesizedProfile] = useState<string | null>(null);
  const [direction, setDirection] = useState(1);

  // On mount (once the auth guard confirms the user is signed in), fetch
  // any partial profile already saved by a previous visit to this wizard —
  // handleNext persists progress after every step, so a refresh mid-wizard
  // resumes where the user left off rather than starting over. A 404/empty
  // response (brand-new user) is treated as "start fresh" via the empty
  // catch block below. `cancelled` guards against setting state after
  // unmount if `ready` flips or the component unmounts mid-fetch.
  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    (async () => {
      try {
        const existing = await onboardingApi.get();
        if (cancelled) return;
        setProfile({
          bio: existing.bio ?? "",
          background: existing.background ?? "",
          target_roles: existing.target_roles ?? [],
          experience_level: existing.experience_level ?? "entry",
          skills: existing.skills ?? [],
          goals: existing.goals ?? "",
          learning_style: existing.learning_style ?? "",
          timeline: existing.timeline ?? "",
        });
        setResumeFilename(existing.resume_filename);
        setResumeText(existing.resume_text);
        setSynthesizedProfile(existing.synthesized_profile);
      } catch {
        // No existing profile yet — start fresh.
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready]);

  // Generic field setter shared by every step component — merges a single
  // key/value pair into the `profile` object without each step needing its
  // own setState wiring.
  function update<K extends keyof ProfileIn>(key: K, value: ProfileIn[K]) {
    setProfile((p) => ({ ...p, [key]: value }));
  }

  // Central step-transition function. Derives the slide animation
  // `direction` (+1 = forward/slide-from-right, -1 = backward/slide-from-
  // left) by comparing the target step to the current one, then commits the
  // new step. Both Back and Continue funnel through this so direction stays
  // consistent.
  function goTo(next: number) {
    setDirection(next > step ? 1 : -1);
    setStep(next);
  }

  // Per-step required-field validation, run before advancing past steps 1-3
  // (step 4/review has no free-text validation — see handleFinish, which is
  // gated on `synthesizedProfile` existing instead). Returns the first
  // validation error message found, or null if the current step is valid.
  function validateStep(): string | null {
    if (step === 1) {
      if (!profile.bio.trim()) return "Tell us a bit about yourself.";
      if (!profile.background.trim()) return "Add your education/work background.";
    }
    if (step === 2) {
      if (profile.target_roles.length === 0) return "Add at least one target role.";
      if (!profile.timeline.trim()) return "Let us know your timeline.";
    }
    if (step === 3) {
      if (profile.skills.length === 0) return "Add at least one skill.";
    }
    return null;
  }

  // Continue-button handler: validates the current step, persists the
  // in-progress profile to the backend (so it survives a refresh — see the
  // mount effect above), then advances to the next step via goTo.
  async function handleNext() {
    const error = validateStep();
    if (error) {
      toast.error(error);
      return;
    }
    if (step < TOTAL_STEPS) {
      setSaving(true);
      try {
        await onboardingApi.update(profile);
        goTo(step + 1);
      } catch (err) {
        toast.error(err instanceof ApiError ? err.message : "Failed to save your profile");
      } finally {
        setSaving(false);
      }
    }
  }

  // Step-4 "Generate my profile" / "Regenerate" handler: saves the latest
  // profile fields, then asks the backend to synthesize a free-text summary
  // (`synthesized_profile`) that becomes the agent's long-term memory of
  // this user. Can be called repeatedly to regenerate after edits.
  async function handleSynthesize() {
    setSynthesizing(true);
    try {
      await onboardingApi.update(profile);
      const res = await onboardingApi.synthesize();
      setSynthesizedProfile(res.synthesized_profile);
      toast.success("Your profile is ready");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to generate your profile");
    } finally {
      setSynthesizing(false);
    }
  }

  // Final "Finish" handler: marks onboarding complete on the backend,
  // refreshes the cached auth user via AuthProvider's `refresh` (so
  // `requireOnboarding` guards elsewhere immediately see the updated flag
  // instead of racing a stale cached value), then navigates to /dashboard.
  async function handleFinish() {
    setSaving(true);
    try {
      await onboardingApi.update({ ...profile, onboarding_completed: true });
      await refresh();
      router.push("/dashboard");
    } finally {
      setSaving(false);
    }
  }

  if (!ready || loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-label="Loading" />
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center px-4 py-12">
      <div className="mb-8 text-center">
        <span className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-accent text-white">
          <Sparkles className="h-5 w-5" aria-hidden="true" />
        </span>
        <h1 className="mt-4 text-2xl font-semibold">Let&apos;s set up your profile</h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          A few details help the agent tailor everything it writes for you.
        </p>
      </div>

      <div className="mb-8">
        <WizardProgress step={step} />
      </div>

      <div className="rounded-2xl border border-border bg-card p-6 shadow-sm sm:p-8">
        <AnimatePresence mode="wait" custom={direction}>
          <motion.div
            key={step}
            custom={direction}
            initial={{ opacity: 0, x: direction * 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: direction * -24 }}
            transition={{ duration: 0.25, ease: "easeOut" }}
          >
            {step === 1 && (
              <StepBackground profile={profile} update={update} />
            )}
            {step === 2 && <StepRoles profile={profile} update={update} />}
            {step === 3 && (
              <StepSkills
                profile={profile}
                update={update}
                resumeFilename={resumeFilename}
                resumeText={resumeText}
                onResumeUploaded={(f, t) => {
                  setResumeFilename(f);
                  setResumeText(t);
                }}
                onResumeClear={() => {
                  setResumeFilename(null);
                  setResumeText(null);
                }}
              />
            )}
            {step === 4 && (
              <StepReview
                profile={profile}
                synthesizedProfile={synthesizedProfile}
                synthesizing={synthesizing}
                onSynthesize={handleSynthesize}
                onEditProfile={setSynthesizedProfile}
              />
            )}
          </motion.div>
        </AnimatePresence>

        <div className="mt-8 flex items-center justify-between border-t border-border pt-6">
          <Button
            variant="ghost"
            onClick={() => goTo(step - 1)}
            disabled={step === 1 || saving}
            className={step === 1 ? "invisible" : ""}
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back
          </Button>
          {step < TOTAL_STEPS ? (
            <Button onClick={handleNext} loading={saving}>
              Continue
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          ) : (
            <Button onClick={handleFinish} loading={saving} disabled={!synthesizedProfile}>
              Finish
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Shared label+hint+content wrapper used by every wizard step below.
 * `children` may be a plain node, or a render-prop `(id) => node` for inputs
 * that need to receive the generated id to wire up `htmlFor`/`id`
 * association explicitly (see the comment inside the function body — this
 * is the fix for the onboarding label/chip-deletion bug referenced in the
 * project's recent commit history: a ChipInput field previously broke when
 * wrapped in a real `<label>`).
 */
function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode | ((id: string) => React.ReactNode);
}) {
  // Plain <div>, not <label> — wrapping a ChipInput (or any field with
  // multiple labelable descendants) in a <label> makes the browser forward
  // activation clicks/:hover to the FIRST labelable descendant, which for a
  // ChipInput with existing chips is the first chip's remove button. That
  // caused clicking/hovering anywhere in the field to hit chip 1's ✕.
  // Instead we associate the label explicitly via htmlFor/id, and let
  // callers that want click-to-focus pass a render-prop to receive the id.
  const id = useId();
  const content = typeof children === "function" ? children(id) : children;
  return (
    <div className="block">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {hint && <span className="ml-1.5 text-xs text-muted-foreground">{hint}</span>}
      <div className="mt-1.5">{content}</div>
    </div>
  );
}

/** Wizard step 1/4: free-text bio and education/work background. */
function StepBackground({
  profile,
  update,
}: {
  profile: ProfileIn;
  update: <K extends keyof ProfileIn>(key: K, value: ProfileIn[K]) => void;
}) {
  return (
    <div className="space-y-5">
      <h2 className="text-lg font-semibold">Tell us about yourself</h2>
      <Field label="Bio" hint="A short introduction">
        {(id) => (
          <Textarea
            id={id}
            rows={3}
            value={profile.bio}
            onChange={(e) => update("bio", e.target.value)}
            placeholder="I'm a self-taught developer looking to break into backend engineering…"
          />
        )}
      </Field>
      <Field label="Background" hint="Education & work history">
        {(id) => (
          <Textarea
            id={id}
            rows={4}
            value={profile.background}
            onChange={(e) => update("background", e.target.value)}
            placeholder="BS in Computer Science, 2 years as a frontend engineer at a startup…"
          />
        )}
      </Field>
    </div>
  );
}

/**
 * Wizard step 2/4: target roles (chip input — see `Field`'s docblock for
 * why chip fields use the render-prop id pattern), experience level, and
 * interview timeline.
 */
function StepRoles({
  profile,
  update,
}: {
  profile: ProfileIn;
  update: <K extends keyof ProfileIn>(key: K, value: ProfileIn[K]) => void;
}) {
  return (
    <div className="space-y-5">
      <h2 className="text-lg font-semibold">Target roles & timeline</h2>
      <Field label="Target roles" hint="Press Enter to add">
        <ChipInput
          values={profile.target_roles}
          onChange={(v) => update("target_roles", v)}
          placeholder="e.g. Backend Engineer, Staff SWE"
        />
      </Field>
      <Field label="Experience level">
        {(id) => (
          <Select
            id={id}
            value={profile.experience_level}
            onChange={(e) => update("experience_level", e.target.value as ExperienceLevel)}
          >
            {EXPERIENCE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label="Timeline" hint="When is your interview?">
        {(id) => (
          <Input
            id={id}
            value={profile.timeline}
            onChange={(e) => update("timeline", e.target.value)}
            placeholder="e.g. Interview in 3 weeks"
          />
        )}
      </Field>
    </div>
  );
}

/**
 * Wizard step 3/4: skills (chip input), goals, optional learning style, and
 * an optional resume upload via `ResumeDropzone`. Resume state
 * (`resumeFilename`/`resumeText`) is lifted to the page component rather
 * than owned locally, since it's independent of the rest of `ProfileIn` and
 * is surfaced back up through the `onResumeUploaded`/`onResumeClear`
 * callbacks.
 */
function StepSkills({
  profile,
  update,
  resumeFilename,
  resumeText,
  onResumeUploaded,
  onResumeClear,
}: {
  profile: ProfileIn;
  update: <K extends keyof ProfileIn>(key: K, value: ProfileIn[K]) => void;
  resumeFilename: string | null;
  resumeText: string | null;
  onResumeUploaded: (filename: string, text: string) => void;
  onResumeClear: () => void;
}) {
  return (
    <div className="space-y-5">
      <h2 className="text-lg font-semibold">Skills & goals</h2>
      <Field label="Skills" hint="Press Enter to add">
        <ChipInput
          values={profile.skills}
          onChange={(v) => update("skills", v)}
          placeholder="e.g. Python, System Design, React"
        />
      </Field>
      <Field label="Goals">
        {(id) => (
          <Textarea
            id={id}
            rows={2}
            value={profile.goals}
            onChange={(e) => update("goals", e.target.value)}
            placeholder="What does success look like for you?"
          />
        )}
      </Field>
      <Field label="Learning style" hint="Optional">
        {(id) => (
          <Input
            id={id}
            value={profile.learning_style}
            onChange={(e) => update("learning_style", e.target.value)}
            placeholder="e.g. Visual, hands-on, reading deep dives"
          />
        )}
      </Field>
      <Field label="Resume" hint="Optional but recommended">
        <ResumeDropzone
          resumeFilename={resumeFilename}
          resumeText={resumeText}
          onUploaded={onResumeUploaded}
          onClear={onResumeClear}
        />
      </Field>
    </div>
  );
}

/**
 * Wizard step 4/4: read-only summary of steps 1-3, plus the
 * generate/regenerate action for the AI-synthesized profile summary. Before
 * synthesis, shows a call-to-action card; after synthesis, shows the
 * generated text in an editable `Textarea` (edits flow back up via
 * `onEditProfile` and are what actually gets saved on Finish) alongside a
 * "Regenerate" button that re-runs synthesis from the current field values.
 */
function StepReview({
  profile,
  synthesizedProfile,
  synthesizing,
  onSynthesize,
  onEditProfile,
}: {
  profile: ProfileIn;
  synthesizedProfile: string | null;
  synthesizing: boolean;
  onSynthesize: () => void;
  onEditProfile: (value: string) => void;
}) {
  return (
    <div className="space-y-5">
      <h2 className="text-lg font-semibold">Review & synthesize</h2>
      <div className="grid gap-3 rounded-lg border border-border bg-muted/30 p-4 text-sm sm:grid-cols-2">
        <SummaryItem label="Target roles" value={profile.target_roles.join(", ") || "—"} />
        <SummaryItem label="Timeline" value={profile.timeline || "—"} />
        <SummaryItem label="Skills" value={profile.skills.join(", ") || "—"} />
        <SummaryItem label="Experience" value={profile.experience_level} />
      </div>

      {!synthesizedProfile ? (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border p-8 text-center">
          <p className="text-sm text-muted-foreground">
            Generate an AI profile summary the agent will use to personalize your curricula.
          </p>
          <Button onClick={onSynthesize} loading={synthesizing}>
            <Sparkles className="h-4 w-4" aria-hidden="true" />
            Generate my profile
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Your synthesized profile</span>
            <Button variant="ghost" size="sm" onClick={onSynthesize} loading={synthesizing}>
              <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
              Regenerate
            </Button>
          </div>
          <Textarea
            rows={8}
            value={synthesizedProfile}
            onChange={(e) => onEditProfile(e.target.value)}
            className="text-sm leading-relaxed"
          />
          <p className="text-xs text-muted-foreground">
            Feel free to edit before finishing — this becomes the agent&apos;s memory of you.
          </p>
        </div>
      )}
    </div>
  );
}

/** Small label/value pair used in StepReview's read-only summary grid. */
function SummaryItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-medium">{value}</p>
    </div>
  );
}
