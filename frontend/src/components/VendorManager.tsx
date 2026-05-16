import { useCallback, useEffect, useState } from "react";

import { approveVendor, getVendors, removeVendor } from "../api";
import type { Vendor } from "../types";

export default function VendorManager() {
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [newName, setNewName] = useState("");
  const [adding, setAdding] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => getVendors().then(setVendors), []);

  useEffect(() => {
    load().finally(() => setLoading(false));
  }, [load]);

  async function handleAdd() {
    const trimmed = newName.trim();
    if (!trimmed) return;
    setAdding(true);
    try {
      await approveVendor(trimmed);
      setNewName("");
      await load();
    } finally {
      setAdding(false);
    }
  }

  async function handleRemove(id: string) {
    try {
      await removeVendor(id);
      await load();
    } catch {
      /* handled silently — row may be constrained in future */
    }
  }

  return (
    <section className="card p-6">
      <h2 className="text-sm font-semibold text-white">Approved vendor list</h2>
      <p className="mt-1 text-xs text-slate-400">
        Fraud stage 1 treats unknown / unapproved names as{" "}
        <span className="mono text-[11px]">new_vendor</span>. Entries are stored upper-case
        with spaces as underscores — matching extraction normalization before LLM reasoning.
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        <input
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void handleAdd();
          }}
          placeholder='e.g. Hall-Boyd LLP → stored as HALL-BOYD_LLP'
          className="min-w-[200px] flex-1 rounded-xl border border-white/10 bg-ink-900/80 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-veridian-500/50 focus:outline-none focus:ring-1 focus:ring-veridian-500/30"
        />
        <button
          type="button"
          onClick={() => void handleAdd()}
          disabled={adding || !newName.trim()}
          className="btn btn-primary px-4 py-2 text-sm disabled:opacity-50"
        >
          {adding ? "Adding…" : "+ Add / approve"}
        </button>
      </div>

      <div className="mt-4 max-h-64 space-y-1 overflow-y-auto pr-1">
        {loading && (
          <p className="py-3 text-xs text-slate-500">Loading vendors…</p>
        )}
        {!loading && vendors.length === 0 && (
          <p className="py-3 text-xs text-slate-500">
            No vendor rows yet. Seed with{" "}
            <span className="mono">python -m scripts.seed_db</span> or add one above / from
            the dashboard prompt after upload.
          </p>
        )}
        {vendors.map((v) => (
          <div
            key={v.id}
            className="flex items-center justify-between gap-2 rounded-xl border border-white/5 bg-white/[0.03] px-3 py-2 text-sm"
          >
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span
                className={
                  v.is_approved ? "text-veridian-400" : "text-slate-500"
                }
              >
                {v.is_approved ? "✓" : "○"}
              </span>
              <span className="mono truncate text-veridian-100">{v.name}</span>
              {v.invoice_count > 0 && (
                <span className="text-[11px] tabular-nums text-slate-500">
                  {v.invoice_count} invoice(s)
                </span>
              )}
              {!v.is_approved && (
                <span className="pill bg-rose-500/15 text-[11px] text-rose-200 ring-1 ring-rose-500/35">
                  suspicious
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={() => void handleRemove(v.id)}
              className="shrink-0 text-[11px] text-slate-500 transition-colors hover:text-rose-400"
            >
              remove
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}
