"use client";

import { useCallback, useState } from "react";
import { useDropzone, type FileRejection } from "react-dropzone";
import { FileText, Loader2, UploadCloud, X } from "lucide-react";
import { toast } from "sonner";
import { onboardingApi, ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

const ACCEPTED = {
  "application/pdf": [".pdf"],
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
  "text/plain": [".txt"],
};
const MAX_SIZE = 5 * 1024 * 1024;

interface ResumeDropzoneProps {
  resumeFilename: string | null;
  resumeText: string | null;
  onUploaded: (filename: string, text: string) => void;
  onClear: () => void;
}

export function ResumeDropzone({
  resumeFilename,
  resumeText,
  onUploaded,
  onClear,
}: ResumeDropzoneProps) {
  const [uploading, setUploading] = useState(false);

  const onDrop = useCallback(
    async (accepted: File[], rejections: FileRejection[]) => {
      if (rejections.length > 0) {
        toast.error(rejections[0].errors[0]?.message ?? "File rejected");
        return;
      }
      const file = accepted[0];
      if (!file) return;
      setUploading(true);
      try {
        const res = await onboardingApi.uploadResume(file);
        onUploaded(res.resume_filename, res.resume_text);
        toast.success("Resume uploaded and parsed");
      } catch (err) {
        toast.error(err instanceof ApiError ? err.message : "Failed to upload resume");
      } finally {
        setUploading(false);
      }
    },
    [onUploaded]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPTED,
    maxSize: MAX_SIZE,
    maxFiles: 1,
    disabled: uploading,
  });

  if (resumeFilename) {
    return (
      <div className="rounded-lg border border-border bg-muted/40 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">
              <FileText className="h-4 w-4" aria-hidden="true" />
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{resumeFilename}</p>
              <p className="text-xs text-muted-foreground">Parsed and ready</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClear}
            aria-label="Remove resume"
            className="shrink-0 rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        {resumeText && (
          <p className="mt-3 max-h-24 overflow-y-auto rounded-md bg-card p-2.5 text-xs leading-relaxed text-muted-foreground scrollbar-thin">
            {resumeText.slice(0, 400)}
            {resumeText.length > 400 ? "…" : ""}
          </p>
        )}
      </div>
    );
  }

  return (
    <div
      {...getRootProps()}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-8 text-center transition-colors",
        isDragActive ? "border-accent bg-accent-soft/50" : "border-border hover:border-accent/50",
        uploading && "pointer-events-none opacity-70"
      )}
    >
      <input {...getInputProps()} aria-label="Upload resume" />
      {uploading ? (
        <Loader2 className="h-6 w-6 animate-spin text-accent" aria-hidden="true" />
      ) : (
        <UploadCloud className="h-6 w-6 text-muted-foreground" aria-hidden="true" />
      )}
      <p className="text-sm font-medium">
        {uploading ? "Uploading…" : "Drag & drop your resume, or click to browse"}
      </p>
      <p className="text-xs text-muted-foreground">PDF, DOCX, or TXT — up to 5MB</p>
    </div>
  );
}
