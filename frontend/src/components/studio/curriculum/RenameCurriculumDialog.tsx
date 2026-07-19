"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Input";
import { curriculaApi, ApiError } from "@/lib/api";
import type { CurriculumSummary } from "@/lib/types";

// Hard caps mirrored from the backend (see backend/app/api/curricula.py's
// _TITLE_MAX_LEN/_DESCRIPTION_MAX_LEN, which mirror the agent-tool bounds).
const TITLE_MAX_LEN = 100;
const DESCRIPTION_MAX_LEN = 500;

interface RenameCurriculumDialogProps {
  open: boolean;
  curriculum: { id: string; title: string; description: string };
  onClose: () => void;
  /** Called with the PATCH response after a successful save, so the caller can update its own state. */
  onSaved: (updated: CurriculumSummary) => void;
}

/**
 * Modal dialog for renaming a curriculum's title/description, modeled on
 * `ConfirmDialog` (same backdrop/animation/Escape-to-close/`role="dialog"`
 * conventions). Local input state is reset from `curriculum` every time
 * `open` flips true, so reopening for a different curriculum (or the same
 * one after an external update) always starts from the current values. On
 * Save, only the fields that actually changed are sent to
 * `curriculaApi.update`; if nothing changed, the dialog just closes without
 * a network call.
 */
export function RenameCurriculumDialog({
  open,
  curriculum,
  onClose,
  onSaved,
}: RenameCurriculumDialogProps) {
  const [title, setTitle] = useState(curriculum.title);
  const [description, setDescription] = useState(curriculum.description);
  const [saving, setSaving] = useState(false);

  // Reseed local state from the current curriculum every time the dialog opens.
  useEffect(() => {
    if (open) {
      setTitle(curriculum.title);
      setDescription(curriculum.description);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only reseed on the open transition
  }, [open]);

  // Escape closes, matching ConfirmDialog's behavior.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  async function handleSave() {
    const trimmedTitle = title.trim();
    const fields: { title?: string; description?: string } = {};
    if (trimmedTitle !== curriculum.title) fields.title = trimmedTitle;
    if (description !== curriculum.description) fields.description = description;

    if (Object.keys(fields).length === 0) {
      onClose(); // nothing changed — no need to hit the API
      return;
    }

    setSaving(true);
    try {
      const updated = await curriculaApi.update(curriculum.id, fields);
      onSaved(updated);
      toast.success("Curriculum renamed");
      onClose();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to rename curriculum");
    } finally {
      setSaving(false);
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby="rename-curriculum-title"
            initial={{ opacity: 0, scale: 0.95, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 8 }}
            transition={{ duration: 0.18 }}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-lg rounded-xl border border-border bg-card p-5 shadow-lg"
          >
            <h2 id="rename-curriculum-title" className="text-base font-semibold">
              Rename curriculum
            </h2>

            <div className="mt-4 space-y-3">
              <div>
                <label htmlFor="rename-curriculum-name" className="mb-1 block text-xs font-medium text-muted-foreground">
                  Name
                </label>
                <Input
                  id="rename-curriculum-name"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  maxLength={TITLE_MAX_LEN}
                  autoFocus
                />
              </div>
              <div>
                <label htmlFor="rename-curriculum-description" className="mb-1 block text-xs font-medium text-muted-foreground">
                  Description
                </label>
                <Textarea
                  id="rename-curriculum-description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  maxLength={DESCRIPTION_MAX_LEN}
                  rows={6}
                />
              </div>
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>
                Cancel
              </Button>
              <Button
                variant="primary"
                size="sm"
                onClick={handleSave}
                loading={saving}
                disabled={title.trim().length === 0}
              >
                Save
              </Button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
