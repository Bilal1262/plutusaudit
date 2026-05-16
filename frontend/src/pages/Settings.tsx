import { useEffect, useState } from "react";
import clsx from "clsx";
import { CheckCircle2, XCircle } from "lucide-react";

import { getHealth } from "../api";

import VendorManager from "../components/VendorManager";

const EU_AI_ACT_CHECKS = [
  "SHA-256 hash-chained audit trail",
  "Human-readable reasoning stored per agent decision",
  "Confidence scores with fixed escalation thresholds",
  "Model name + software version stamped on audit entries",
  "Human override produces a new append-only audit record",
  "Destructive edits blocked — invoices use immutable audit chain",
] as const;

export default function Settings() {
  const [health, setHealth] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [euChecks, setEuChecks] = useState<boolean[]>(() =>
    EU_AI_ACT_CHECKS.map(() => true),
  );

  useEffect(() => {
    getHealth()
      .then((h) => setHealth(h))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <section>
        <h1 className="text-2xl font-bold tracking-tight text-white">
          Settings & Health
        </h1>
        <p className="mt-1 text-sm text-slate-400 max-w-2xl">
          Operational view of the running deployment. The thresholds and chart
          of accounts live in <span className="mono">backend/config.py</span>.
        </p>
      </section>

      <section className="card p-6">
        <h2 className="text-sm font-semibold text-white">System health</h2>
        {loading ? (
          <div className="mt-3 text-sm text-slate-400">Loading…</div>
        ) : (
          <div className="mt-4 grid grid-cols-1 md:grid-cols-4 gap-3">
            <HealthCard
              label="API"
              ok={health?.status === "ok"}
              value={health?.version || "—"}
            />
            <HealthCard
              label="RAG index"
              ok={!!health?.rag_loaded}
              value={health?.rag_loaded ? "loaded" : "not loaded"}
            />
            <HealthCard
              label="Database"
              ok={!!health?.db_connected}
              value={health?.db_connected ? "connected" : "fallback"}
            />
            <HealthCard
              label="Environment"
              ok={!!health?.env}
              value={health?.env ?? "—"}
            />
          </div>
        )}
      </section>

      <section className="card p-6">
        <h2 className="text-sm font-semibold text-white">
          EU AI Act · demo checklist
        </h2>
        <p className="mt-1 text-xs text-slate-400 max-w-2xl">
          Lightweight governance markers for stakeholder demos (EU AI Act Annex IV,
          GDPR Art. 22 transparency themes, SOX-style control narrative). Toggle to
          rehearse readiness conversations — state stays in this browser session
          only.
        </p>
        <ul className="mt-4 space-y-3">
          {EU_AI_ACT_CHECKS.map((label, idx) => (
            <li key={label}>
              <label className="flex cursor-pointer items-start gap-3 text-sm text-slate-200">
                <input
                  type="checkbox"
                  className="mt-1 h-4 w-4 rounded border-white/20 bg-ink-900 text-veridian-500 focus:ring-veridian-500/40"
                  checked={euChecks[idx]}
                  onChange={() =>
                    setEuChecks((prev) =>
                      prev.map((v, i) => (i === idx ? !v : v)),
                    )
                  }
                />
                <span>{label}</span>
              </label>
            </li>
          ))}
        </ul>
      </section>

      <VendorManager />
    </div>
  );
}

function HealthCard({
  label,
  ok,
  value,
}: {
  label: string;
  ok: boolean;
  value: string;
}) {
  return (
    <div
      className={clsx(
        "rounded-xl p-4 ring-1",
        ok
          ? "bg-veridian-500/10 ring-veridian-500/30 text-veridian-100"
          : "bg-rose-500/10 ring-rose-500/30 text-rose-100",
      )}
    >
      <div className="flex items-center gap-2 text-xs uppercase tracking-widest opacity-80">
        {ok ? (
          <CheckCircle2 className="h-3.5 w-3.5" />
        ) : (
          <XCircle className="h-3.5 w-3.5" />
        )}
        {label}
      </div>
      <div className="mt-1 text-sm font-semibold">{value}</div>
    </div>
  );
}
