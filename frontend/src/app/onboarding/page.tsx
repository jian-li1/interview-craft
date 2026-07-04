"use client";

import { useEffect, useState } from "react";
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

  function update<K extends keyof ProfileIn>(key: K, value: ProfileIn[K]) {
    setProfile((p) => ({ ...p, [key]: value }));
  }

  function goTo(next: number) {
    setDirection(next > step ? 1 : -1);
    setStep(next);
  }

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

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm font-medium">{label}</span>
      {hint && <span className="ml-1.5 text-xs text-muted-foreground">{hint}</span>}
      <div className="mt-1.5">{children}</div>
    </label>
  );
}

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
        <Textarea
          rows={3}
          value={profile.bio}
          onChange={(e) => update("bio", e.target.value)}
          placeholder="I'm a self-taught developer looking to break into backend engineering…"
        />
      </Field>
      <Field label="Background" hint="Education & work history">
        <Textarea
          rows={4}
          value={profile.background}
          onChange={(e) => update("background", e.target.value)}
          placeholder="BS in Computer Science, 2 years as a frontend engineer at a startup…"
        />
      </Field>
    </div>
  );
}

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
        <Select
          value={profile.experience_level}
          onChange={(e) => update("experience_level", e.target.value as ExperienceLevel)}
        >
          {EXPERIENCE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Timeline" hint="When is your interview?">
        <Input
          value={profile.timeline}
          onChange={(e) => update("timeline", e.target.value)}
          placeholder="e.g. Interview in 3 weeks"
        />
      </Field>
    </div>
  );
}

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
        <Textarea
          rows={2}
          value={profile.goals}
          onChange={(e) => update("goals", e.target.value)}
          placeholder="What does success look like for you?"
        />
      </Field>
      <Field label="Learning style" hint="Optional">
        <Input
          value={profile.learning_style}
          onChange={(e) => update("learning_style", e.target.value)}
          placeholder="e.g. Visual, hands-on, reading deep dives"
        />
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

function SummaryItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-medium">{value}</p>
    </div>
  );
}
