import clsx from "clsx";
import { CheckCircle2, ShieldAlert } from "lucide-react";

import type { ChainVerifyResult } from "../types";

interface Props {
  result?: ChainVerifyResult | null;
}

export default function TamperDetectBanner({ result }: Props) {
  if (!result) return null;
  const ok = !!result.valid;
  return (
    <div
      className={clsx(
        "rounded-2xl border p-4 flex items-start gap-3",
        ok
          ? "bg-veridian-500/10 border-veridian-500/40 text-veridian-100"
          : "bg-rose-500/15 border-rose-500/60 text-rose-100 animate-pulse-fast",
      )}
    >
      {ok ? (
        <CheckCircle2 className="h-6 w-6 mt-0.5 text-veridian-300" />
      ) : (
        <ShieldAlert className="h-6 w-6 mt-0.5 text-rose-300" />
      )}

      <div className="flex-1">
        <div className="text-sm font-semibold">
          {ok
            ? `Audit chain verified — ${result.count ?? 0} entries intact`
            : `AUDIT CHAIN INTEGRITY VIOLATION — Entry #${
                result.broken_at_sequence ?? "?"
              } has been tampered with`}
        </div>
        {!ok && (
          <div className="mt-1 text-xs space-y-0.5 text-rose-200/90">
            <div>{result.reason}</div>
            {result.expected_prev_hash && (
              <div className="mono break-all">
                expected prev_hash: {result.expected_prev_hash.slice(0, 24)}…
              </div>
            )}
            {result.found_prev_hash && (
              <div className="mono break-all">
                found prev_hash: {result.found_prev_hash.slice(0, 24)}…
              </div>
            )}
            {result.expected_entry_hash && (
              <div className="mono break-all">
                expected entry_hash: {result.expected_entry_hash.slice(0, 24)}…
              </div>
            )}
            {result.found_entry_hash && (
              <div className="mono break-all">
                found entry_hash: {result.found_entry_hash.slice(0, 24)}…
              </div>
            )}
            <div className="mt-1 italic">
              This log can no longer be trusted. Restore from immutable backup.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
