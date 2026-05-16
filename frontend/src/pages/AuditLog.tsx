import { useCallback, useEffect, useState } from "react";

import { getAuditLog } from "../api";
import AuditTrailViewer from "../components/AuditTrailViewer";
import type { AuditEntry } from "../types";

export default function AuditLog() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getAuditLog(1, 100);
      // Backend returns newest first; flip to chronological for the chain view.
      setEntries([...data.items].reverse());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <div className="space-y-6">
      <section>
        <h1 className="text-2xl font-bold tracking-tight text-white">
          Audit Log
        </h1>
        <p className="mt-1 text-sm text-slate-400 max-w-2xl">
          Every agent decision is appended to a SHA-256 hash chain. Click{" "}
          <span className="mono">Verify Chain Integrity</span> to replay the
          chain. Click <span className="mono">Simulate tamper</span> to mutate a
          row directly in Postgres and watch the system catch it.
        </p>
      </section>

      {loading ? (
        <div className="card p-6 text-sm text-slate-400">Loading entries…</div>
      ) : (
        <AuditTrailViewer entries={entries} onChange={refresh} />
      )}
    </div>
  );
}
