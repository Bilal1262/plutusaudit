import { useEffect, useState } from "react";
import clsx from "clsx";
import { ClipboardList, Eye } from "lucide-react";

import { getInvoiceHistory } from "../api";
import type { Invoice } from "../types";

function tierClass(status: string, tier?: string | null) {
  if (status === "blocked" || tier === "block")
    return "bg-rose-500/15 text-rose-200 ring-rose-500/40";
  if (status === "flagged" || tier === "review")
    return "bg-amber-500/15 text-amber-200 ring-amber-500/40";
  return "bg-veridian-500/15 text-veridian-200 ring-veridian-500/40";
}

export default function ReviewQueue() {
  const [items, setItems] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      const data = await getInvoiceHistory(1, 100);
      // Only flagged / blocked / requires review
      const filtered = data.filter(
        (d) => d.status === "flagged" || d.status === "blocked" || d.fraud_tier === "review",
      );
      // Keep only the latest run per filename so the queue reflects the current
      // operational state for each submitted document.
      const latestByFilename = new Map<string, Invoice>();
      for (const inv of filtered) {
        if (!latestByFilename.has(inv.filename)) {
          latestByFilename.set(inv.filename, inv);
        }
      }
      setItems(Array.from(latestByFilename.values()));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <section className="card p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm">
          <ClipboardList className="h-4 w-4 text-veridian-300" />
          <span className="font-semibold text-white">Human Review Queue</span>
          <span className="text-slate-500">·</span>
          <span className="text-slate-400 text-xs">
            Invoices flagged by the verifier or fraud agent
          </span>
        </div>
        <button onClick={refresh} className="btn-ghost text-xs">
          Refresh
        </button>
      </div>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-slate-400">
            <tr>
              <th className="text-left py-2 px-2">Filename</th>
              <th className="text-left py-2 px-2">Vendor</th>
              <th className="text-left py-2 px-2">Amount</th>
              <th className="text-left py-2 px-2">Status</th>
              <th className="text-left py-2 px-2">Fraud</th>
              <th className="text-left py-2 px-2">Action</th>
            </tr>
          </thead>
          <tbody>
            {loading && (
              <tr>
                <td colSpan={6} className="py-4 text-slate-400 text-center">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={6} className="py-4 text-slate-400 text-center">
                  No invoices currently require manual review.
                </td>
              </tr>
            )}
            {items.map((inv) => (
              <tr
                key={inv.id}
                className="border-t border-white/5 hover:bg-white/5"
              >
                <td className="py-2 px-2 mono text-xs text-slate-300">
                  {inv.filename}
                </td>
                <td className="py-2 px-2 text-slate-200">{inv.vendor_name ?? "—"}</td>
                <td className="py-2 px-2 text-slate-200 tabular-nums">
                  {inv.grand_total != null
                    ? `${inv.currency} ${Number(inv.grand_total).toFixed(2)}`
                    : "—"}
                </td>
                <td className="py-2 px-2">
                  <span
                    className={clsx(
                      "pill ring-1",
                      tierClass(inv.status, inv.fraud_tier),
                    )}
                  >
                    {inv.status}
                  </span>
                </td>
                <td className="py-2 px-2 text-slate-300">
                  {inv.fraud_tier ?? "—"}{" "}
                  <span className="text-slate-500 mono text-[11px]">
                    ({inv.fraud_score ?? 0})
                  </span>
                </td>
                <td className="py-2 px-2">
                  <a
                    href={`/audit?invoice=${inv.id}`}
                    className="btn-ghost text-xs"
                  >
                    <Eye className="h-3.5 w-3.5" />
                    Inspect
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
