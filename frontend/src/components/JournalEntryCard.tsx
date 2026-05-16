import { Scale } from "lucide-react";
import type { AccountantResult } from "../types";
import { pickCitationChunk } from "../utils/pickCitationChunk";
import CitationCard from "./CitationCard";

interface Props {
  accountant: AccountantResult;
  currency?: string;
  onOverride?: () => void;
}

function fmt(amount: number, currency?: string) {
  if (!currency || currency.length !== 3) {
    return amount.toFixed(2);
  }
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${currency} ${amount.toFixed(2)}`;
  }
}

export default function JournalEntryCard({
  accountant,
  currency,
  onOverride,
}: Props) {
  const amount = Number(accountant.amount || 0);
  const citationChunk = pickCitationChunk(accountant);
  return (
    <div className="card p-5">
      <div className="flex items-center gap-2 text-sm font-semibold text-white">
        <Scale className="h-4 w-4 text-veridian-300" />
        Journal Entry
      </div>

      <div className="mono mt-4 rounded-xl bg-black/40 p-4 text-sm">
        <div className="grid grid-cols-[60px_1fr_auto] gap-y-1 items-baseline">
          <div className="text-veridian-300">DR</div>
          <div className="text-slate-100">{accountant.gl_account_debit}</div>
          <div className="text-slate-100 text-right">{fmt(amount, currency)}</div>

          <div className="text-amber-400">CR</div>
          <div className="text-slate-100 pl-6">
            {accountant.gl_account_credit}
          </div>
          <div className="text-slate-100 text-right">{fmt(amount, currency)}</div>
        </div>
      </div>

      {accountant.deferral_required && accountant.amortization_schedule && (
        <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-100">
          <div className="font-semibold">Deferral / Amortization</div>
          <pre className="mono mt-1 whitespace-pre-wrap text-amber-200/90">
            {JSON.stringify(accountant.amortization_schedule, null, 2)}
          </pre>
        </div>
      )}

      <div className="mt-4">
        <CitationCard
          standard={accountant.standard_cited}
          paragraph={accountant.paragraph_cited}
          chunk={citationChunk}
        />
      </div>

      {onOverride && (
        <div className="mt-4 flex justify-end">
          <button onClick={onOverride} className="btn-ghost">
            Disagree / Override
          </button>
        </div>
      )}
    </div>
  );
}
