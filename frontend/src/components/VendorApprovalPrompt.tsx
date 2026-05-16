import { useState } from "react";

import { approveVendor } from "../api";

interface Props {
  vendorName: string;
  onClose: () => void;
  onApproved?: () => void;
}

export default function VendorApprovalPrompt({
  vendorName,
  onClose,
  onApproved,
}: Props) {
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleApprove() {
    setLoading(true);
    setError(null);
    try {
      await approveVendor(vendorName);
      setDone(true);
      onApproved?.();
    } catch {
      setError("Could not approve vendor. Check that the API is reachable.");
    } finally {
      setLoading(false);
    }
  }

  if (done) {
    return (
      <div className="rounded-2xl border border-veridian-500/35 bg-veridian-500/10 p-4 text-sm">
        <div className="flex flex-wrap items-start gap-3">
          <span className="text-veridian-400">✓</span>
          <div className="min-w-0 flex-1 text-veridian-100">
            <span className="font-semibold text-white">{vendorName}</span>
            {" — "}
            added to the approved vendor list as{" "}
            <span className="mono text-xs opacity-90">
              {vendorName.trim().toUpperCase().replace(/\s+/g, "_")}
            </span>
            . The next invoice from this normalized name will typically clear the
            new-vendor signal.
          </div>
          <button
            type="button"
            onClick={onClose}
            className="btn btn-primary shrink-0 py-1.5 text-xs"
          >
            Got it
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-amber-500/35 bg-amber-500/10 p-4">
      <div className="flex items-start gap-3">
        <span className="text-lg leading-none text-amber-400">⚠</span>
        <div className="min-w-0 flex-1 space-y-2">
          <p className="text-sm font-medium text-amber-100">New vendor detected</p>
          <p className="text-sm text-amber-200/95">
            <span className="font-semibold text-white">{vendorName}</span>
            {""} is not on your approved vendor master. That contributed the{" "}
            <span className="mono text-xs">new_vendor</span> fraud signal on this run.
          </p>
          <p className="text-xs text-amber-200/75">
            Approve now to add them to the tamper-evident vendor list so future invoices
            can auto-match (same normalized vendor key the fraud agent uses).
          </p>
          {error && (
            <p className="text-xs text-rose-300">{error}</p>
          )}
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-2 pl-9">
        <button
          type="button"
          onClick={handleApprove}
          disabled={loading}
          className="btn btn-primary px-4 py-1.5 text-sm disabled:opacity-50"
        >
          {loading ? "Adding…" : "✓ Approve vendor"}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="btn btn-ghost border border-white/10 px-4 py-1.5 text-sm text-slate-200"
        >
          ✗ Keep flagged
        </button>
      </div>
    </div>
  );
}
