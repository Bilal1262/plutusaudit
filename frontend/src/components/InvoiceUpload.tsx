import { useCallback, useRef, useState } from "react";
import clsx from "clsx";
import { FileUp, Loader2, UploadCloud } from "lucide-react";

import { uploadInvoice } from "../api";

interface Props {
  onJobStarted: (jobId: string, file: File) => void;
  disabled?: boolean;
}

const ACCEPT = ".pdf,.png,.jpg,.jpeg,application/pdf,image/*";

export default function InvoiceUpload({ onJobStarted, disabled }: Props) {
  const [dragOver, setDragOver] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    async (file: File) => {
      setError(null);
      setSubmitting(true);
      try {
        const { job_id } = await uploadInvoice(file);
        onJobStarted(job_id, file);
      } catch (err: any) {
        setError(err?.response?.data?.detail || err?.message || "Upload failed");
      } finally {
        setSubmitting(false);
      }
    },
    [onJobStarted],
  );

  return (
    <section
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        const f = e.dataTransfer.files?.[0];
        if (f) handleFile(f);
      }}
      className={clsx(
        "card border-2 border-dashed transition-colors p-8 text-center",
        dragOver
          ? "border-veridian-500 bg-veridian-500/10"
          : "border-white/10 hover:border-white/20",
        disabled && "opacity-60 pointer-events-none",
      )}
    >
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        accept={ACCEPT}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) handleFile(f);
          e.target.value = "";
        }}
      />

      <div className="flex flex-col items-center gap-3">
        <div className="grid h-14 w-14 place-items-center rounded-2xl bg-veridian-600/15 ring-1 ring-veridian-500/40">
          {submitting ? (
            <Loader2 className="h-6 w-6 animate-spin text-veridian-300" />
          ) : (
            <UploadCloud className="h-6 w-6 text-veridian-300" />
          )}
        </div>

        <div className="text-base font-semibold text-white">
          Submit invoice for review
        </div>
        <div className="text-xs text-slate-400 max-w-sm">
          PDF / PNG / JPG accepted. Each submission runs the complete control
          workflow and records a hash-chained audit trail for review.
        </div>

        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={submitting}
          className="btn-primary mt-2"
        >
          <FileUp className="h-4 w-4" />
          {submitting ? "Submitting…" : "Select invoice"}
        </button>

        {error && (
          <div className="mt-2 text-xs text-rose-300 bg-rose-500/10 ring-1 ring-rose-500/30 rounded-md px-3 py-1.5">
            {error}
          </div>
        )}
      </div>
    </section>
  );
}
