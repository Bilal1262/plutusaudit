import { useState } from "react";
import clsx from "clsx";
import { Beaker, Check, Link2, ShieldCheck } from "lucide-react";

import { demoTamper, verifyAuditChain } from "../api";
import type { AuditEntry, ChainVerifyResult } from "../types";
import TamperDetectBanner from "./TamperDetectBanner";

interface Props {
  entries: AuditEntry[];
  onChange?: () => void;
}

function short(s?: string | null, n = 10) {
  if (!s) return "—";
  return s.length <= n * 2 ? s : `${s.slice(0, n)}…${s.slice(-n / 2)}`;
}

function fmtTs(ts?: string) {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export default function AuditTrailViewer({ entries, onChange }: Props) {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ChainVerifyResult | null>(null);

  async function runVerify() {
    setBusy(true);
    try {
      const r = await verifyAuditChain();
      setResult(r);
    } finally {
      setBusy(false);
    }
  }

  async function runTamperDemo() {
    if (!entries.length) return;
    if (!confirm("Run an integrity-control test by mutating one audit row?")) return;
    setBusy(true);
    try {
      // Tamper the middle row (most visually impactful)
      const mid = entries[Math.floor(entries.length / 2)];
      await demoTamper(mid.entry_id);
      await runVerify();
      onChange?.();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm">
          <ShieldCheck className="h-4 w-4 text-veridian-300" />
          <span className="font-semibold text-white">
            Hash-Chained Audit Log
          </span>
          <span className="text-slate-500">·</span>
          <span className="text-slate-400 text-xs">
            SHA-256 chain · append-only · tamper-evident
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={runTamperDemo}
            disabled={busy || entries.length === 0}
            className="btn-ghost text-amber-200"
            title="Run an integrity-control test"
          >
            <Beaker className="h-4 w-4" />
            Test integrity control
          </button>
          <button
            onClick={runVerify}
            disabled={busy}
            className="btn-primary"
          >
            <Check className="h-4 w-4" />
            {busy ? "Verifying…" : "Verify Chain Integrity"}
          </button>
        </div>
      </div>

      <div className="mt-4">
        <TamperDetectBanner result={result} />
      </div>

      <ol className="mt-6 space-y-3 relative pl-6 before:absolute before:left-3 before:top-2 before:bottom-2 before:w-px before:bg-white/10">
        {entries.length === 0 && (
          <div className="text-sm text-slate-400">
            No audit entries yet. Process an invoice to populate the chain.
          </div>
        )}
        {entries.map((e) => {
          const broken =
            result &&
            !result.valid &&
            result.broken_at_sequence === e.sequence;
          return (
            <li key={e.entry_id} className="relative">
              <span
                className={clsx(
                  "absolute -left-[14px] top-2 grid h-4 w-4 place-items-center rounded-full ring-2",
                  broken
                    ? "bg-rose-500 ring-rose-300 animate-pulse-fast"
                    : "bg-veridian-500 ring-veridian-300",
                )}
              />
              <div
                className={clsx(
                  "card p-4",
                  broken && "ring-2 ring-rose-500/60",
                )}
              >
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <div className="flex items-center gap-3">
                    <span className="pill bg-white/5 ring-1 ring-white/10">
                      #{e.sequence}
                    </span>
                    <span className="text-sm font-semibold text-white">
                      {e.agent_name}
                    </span>
                    <span className="text-[11px] text-slate-400">
                      {e.model_name}
                    </span>
                    {e.confidence !== null && (
                      <span className="pill bg-veridian-500/10 ring-1 ring-veridian-500/30 text-veridian-200">
                        conf {Math.round((e.confidence || 0) * 100)}%
                      </span>
                    )}
                  </div>
                  <span className="text-[11px] text-slate-500">
                    {fmtTs(e.timestamp)}
                  </span>
                </div>

                <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3 text-[12px]">
                  <Hash label="input_hash" value={e.input_hash} />
                  <Hash label="entry_hash" value={e.entry_hash} />
                  <Hash label="prev_hash" value={e.prev_hash} />
                </div>
                {e.citations && e.citations.length > 0 && (
                  <div className="mt-3 flex items-center gap-2 flex-wrap text-[11px] text-slate-400">
                    <Link2 className="h-3.5 w-3.5" />
                    {e.citations.slice(0, 6).map((c, i) => (
                      <span
                        key={i}
                        className="pill bg-white/5 ring-1 ring-white/10 mono"
                      >
                        {String(c).slice(0, 24)}
                      </span>
                    ))}
                  </div>
                )}
                {e.human_override && (
                  <div className="mt-3 rounded-lg bg-amber-500/10 ring-1 ring-amber-500/30 p-2 text-[12px] text-amber-200">
                    Human override: {e.human_override}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function Hash({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="rounded-md bg-black/40 p-2">
      <div className="text-[10px] uppercase tracking-wider text-slate-400">
        {label}
      </div>
      <div className="mono mt-0.5 text-veridian-200 break-all">
        {short(value, 12)}
      </div>
    </div>
  );
}
