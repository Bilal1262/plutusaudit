import clsx from "clsx";
import {
  AlarmClock,
  BadgeDollarSign,
  Building2,
  Copy,
  CopyCheck,
  CreditCard,
  FileQuestion,
  Hash,
  Receipt,
  ScrollText,
  ShieldAlert,
} from "lucide-react";

import type { FraudResult, FraudSignals } from "../types";

interface Props {
  fraud: FraudResult;
}

interface SignalMeta {
  key: keyof FraudSignals;
  label: string;
  desc: string;
  icon: JSX.Element;
  fired: (s: FraudSignals) => boolean;
}

const SIGNALS: SignalMeta[] = [
  {
    key: "exact_duplicate",
    label: "Exact duplicate",
    desc: "Identical invoice number + vendor + amount already in the DB.",
    icon: <CopyCheck className="h-4 w-4" />,
    fired: (s) => !!s.exact_duplicate,
  },
  {
    key: "near_duplicate_count",
    label: "Near duplicate",
    desc: "Same vendor, ±1% amount, ±7 days, invoice # Levenshtein ≤ 3.",
    icon: <Copy className="h-4 w-4" />,
    fired: (s) => (s.near_duplicate_count || 0) >= 1,
  },
  {
    key: "benford_flag",
    label: "Benford's Law",
    desc: "Leading-digit MAD > 0.015 vs Benford expectation (Nigrini).",
    icon: <Hash className="h-4 w-4" />,
    fired: (s) => !!s.benford_flag,
  },
  {
    key: "round_number",
    label: "Round number",
    desc: "Amount is a round $500 / $1,000 multiple — common in invented invoices.",
    icon: <BadgeDollarSign className="h-4 w-4" />,
    fired: (s) => !!s.round_number,
  },
  {
    key: "below_threshold",
    label: "Below threshold",
    desc: "Amount lies just below an approval threshold (≤5% margin).",
    icon: <Receipt className="h-4 w-4" />,
    fired: (s) => !!s.below_threshold,
  },
  {
    key: "missing_po",
    label: "Missing PO",
    desc: "No PO number on an invoice over $1,000.",
    icon: <FileQuestion className="h-4 w-4" />,
    fired: (s) => !!s.missing_po,
  },
  {
    key: "vague_description",
    label: "Vague description",
    desc: "Line item descriptions are too short or boilerplate.",
    icon: <ScrollText className="h-4 w-4" />,
    fired: (s) => !!s.vague_description,
  },
  {
    key: "new_vendor",
    label: "New / unapproved vendor",
    desc: "Vendor is not in the approved vendor master.",
    icon: <Building2 className="h-4 w-4" />,
    fired: (s) => !!s.new_vendor,
  },
  {
    key: "off_hours_submission",
    label: "Off-hours submission",
    desc: "Invoice received before 7am or after 8pm UTC.",
    icon: <AlarmClock className="h-4 w-4" />,
    fired: (s) => !!s.off_hours_submission,
  },
  {
    key: "bank_account_change_requested",
    label: "Bank account change",
    desc: "Request to update bank account / routing on the invoice.",
    icon: <CreditCard className="h-4 w-4" />,
    fired: (s) => !!s.bank_account_change_requested,
  },
];

function tierColor(tier: string) {
  if (tier === "block")
    return "bg-rose-500/20 text-rose-200 ring-rose-500/50";
  if (tier === "review")
    return "bg-amber-500/20 text-amber-200 ring-amber-500/50";
  return "bg-veridian-500/20 text-veridian-200 ring-veridian-500/50";
}

function scoreColor(score: number) {
  if (score >= 70) return "text-rose-400";
  if (score >= 30) return "text-amber-300";
  return "text-veridian-300";
}

export default function FraudHeatmap({ fraud }: Props) {
  const signals = fraud.signals;
  const score = fraud.risk_score ?? 0;
  const tier = fraud.tier ?? "clean";
  const explanation = fraud.llm_result?.plain_english_explanation;

  return (
    <section className="card p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm">
          <ShieldAlert className="h-4 w-4 text-veridian-300" />
          <span className="font-semibold text-white">Risk Controls</span>
          <span className="text-slate-500">·</span>
          <span className="text-slate-400 text-xs">
            deterministic controls with model-assisted risk assessment
          </span>
        </div>
        <span
          className={clsx(
            "pill ring-1 uppercase tracking-wider",
            tierColor(tier),
          )}
        >
          {tier}
        </span>
      </div>

      <div className="mt-5 grid grid-cols-1 md:grid-cols-[1fr_auto] gap-6">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
          {SIGNALS.map((sig) => {
            const fired = sig.fired(signals);
            return (
              <div
                key={sig.key}
                title={sig.desc}
                className={clsx(
                  "group relative rounded-xl p-3 ring-1 transition-all",
                  fired
                    ? "bg-rose-500/15 text-rose-100 ring-rose-500/50 shadow-[0_0_0_1px_rgba(244,63,94,0.4)]"
                    : "bg-veridian-500/5 text-veridian-100 ring-veridian-500/30",
                )}
              >
                <div className="flex items-center gap-2 text-xs font-medium">
                  {sig.icon}
                  <span>{sig.label}</span>
                </div>
                <div
                  className={clsx(
                    "mt-2 text-[10px] uppercase tracking-wider",
                    fired ? "text-rose-300" : "text-veridian-400/70",
                  )}
                >
                  {fired ? "fired" : "ok"}
                </div>
                <div className="pointer-events-none absolute left-1/2 top-full z-10 mt-2 hidden w-56 -translate-x-1/2 rounded-md bg-black/90 p-2 text-[11px] text-slate-200 ring-1 ring-white/10 group-hover:block">
                  {sig.desc}
                </div>
              </div>
            );
          })}
        </div>

        <div className="grid place-items-center">
          <div className="text-[10px] uppercase tracking-widest text-slate-400">
            Risk score
          </div>
          <div className={clsx("text-6xl font-bold tabular-nums", scoreColor(score))}>
            {score}
          </div>
          <div className="text-xs text-slate-400">/ 100</div>
        </div>
      </div>

      {explanation && (
        <div className="mt-5 rounded-xl bg-black/30 p-4 text-sm leading-relaxed text-slate-200">
          {explanation}
        </div>
      )}
    </section>
  );
}
