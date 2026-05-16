import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getAnalytics } from "../api";
import type { AnalyticsPayload } from "../types";

const BAR_COLORS = [
  "#14b8a6",
  "#6366f1",
  "#f59e0b",
  "#f43f5e",
  "#a855f7",
  "#06b6d4",
];

export default function Analytics() {
  const [data, setData] = useState<AnalyticsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAnalytics()
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => {
        if (!cancelled) setError("failed");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center rounded-2xl border border-white/5 bg-ink-800/40 py-24 text-sm text-slate-400">
        Loading CFO analytics…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="card border-rose-500/30 bg-rose-500/10 p-8 text-sm text-rose-200">
        Could not load analytics. Confirm the API is running and{" "}
        <Link to="/" className="text-veridian-300 underline underline-offset-2">
          process at least one invoice
        </Link>
        .
      </div>
    );
  }

  const { summary, gl_breakdown, recent_invoices } = data;

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-2xl font-bold tracking-tight text-white">
          CFO Analytics
        </h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-400">
          Live aggregates from PlutusAudit&apos;s invoice pipeline — throughput,
          risk value surfaced before payment, and GL debit concentration.
        </p>
        <p className="mt-2 text-xs text-slate-500">
          Governance checklist:{" "}
          <Link
            to="/settings"
            className="text-veridian-400 hover:text-veridian-300"
          >
            Settings → EU AI Act demo checklist
          </Link>
          .
        </p>
      </section>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard
          label="Touchless rate"
          value={`${summary.touchless_rate}%`}
          sub={`${summary.approved} of ${summary.total_processed} auto-approved`}
          benchmark="vs 30–50% industry average"
          tone="veridian"
        />
        <MetricCard
          label="Avg processing time"
          value={`${summary.avg_processing_seconds}s`}
          sub="invoice intake → audit-ready"
          benchmark="vs 7–10 days manual"
          tone="sky"
        />
        <MetricCard
          label="Fraud value surfaced"
          value={`$${summary.fraud_value_caught.toLocaleString()}`}
          sub={`${(summary.flagged || 0) + (summary.blocked || 0)} invoice(s) flagged or blocked`}
          benchmark="before payment released"
          tone="rose"
        />
        <MetricCard
          label="Cost saved (modeled)"
          value={`$${summary.cost_saved.toLocaleString()}`}
          sub="$0.04 vs $17 per invoice assumption"
          benchmark={`${summary.total_processed} invoices in scope`}
          tone="amber"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <StatusCard label="Auto-approved" count={summary.approved} tone="veridian" />
        <StatusCard label="Flagged for review" count={summary.flagged} tone="amber" />
        <StatusCard label="Blocked" count={summary.blocked} tone="rose" />
      </div>

      <section className="card p-6">
        <h2 className="text-sm font-semibold text-white">
          Spend by GL account (debit)
        </h2>
        <p className="mt-1 text-xs text-slate-400">
          Top accounts by summed journal debit amounts from posted runs.
        </p>
        {gl_breakdown.length > 0 ? (
          <div className="mt-5 h-[240px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={gl_breakdown}
                layout="vertical"
                margin={{ left: 8, right: 24 }}
              >
                <XAxis
                  type="number"
                  tick={{ fill: "#94a3b8", fontSize: 11 }}
                  tickFormatter={(v) =>
                    `$${v >= 1000 ? `${(v / 1000).toFixed(1)}k` : `${v}`}`
                  }
                />
                <YAxis
                  type="category"
                  dataKey="account"
                  width={200}
                  tick={{ fill: "#cbd5e1", fontSize: 11 }}
                />
                <Tooltip
                  formatter={(value: number) => [
                    `$${value.toLocaleString(undefined, {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}`,
                    "Amount",
                  ]}
                  contentStyle={{
                    background: "#0f172a",
                    border: "1px solid rgba(255,255,255,0.08)",
                    borderRadius: 8,
                    color: "#f8fafc",
                  }}
                  labelStyle={{ color: "#94a3b8" }}
                />
                <Bar dataKey="amount" radius={[0, 6, 6, 0]}>
                  {gl_breakdown.map((_, i) => (
                    <Cell key={i} fill={BAR_COLORS[i % BAR_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="mt-4 text-sm text-slate-500">
            No GL journal rows yet — upload invoices to populate this chart.
          </p>
        )}
      </section>

      <section className="card p-6">
        <h2 className="text-sm font-semibold text-white">Recent invoices</h2>
        <p className="mt-1 text-xs text-slate-400">
          Last ten rows by creation time (includes in-flight uploads).
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-2 py-2 text-left">File</th>
                <th className="px-2 py-2 text-left">Vendor</th>
                <th className="px-2 py-2 text-right">Amount</th>
                <th className="px-2 py-2 text-left">Status</th>
                <th className="px-2 py-2 text-right">Fraud</th>
                <th className="px-2 py-2 text-left">Created</th>
              </tr>
            </thead>
            <tbody>
              {recent_invoices.map((inv, idx) => (
                <tr key={`${inv.filename}-${idx}`} className="border-t border-white/5">
                  <td className="max-w-[180px] truncate px-2 py-2 mono text-xs text-veridian-100">
                    {inv.filename}
                  </td>
                  <td className="max-w-[140px] truncate px-2 py-2 text-slate-300">
                    {inv.vendor ?? "—"}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums text-slate-200">
                    {inv.currency}{" "}
                    {inv.amount.toLocaleString(undefined, {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}
                  </td>
                  <td className="px-2 py-2">{statusPill(inv.status)}</td>
                  <td className="px-2 py-2 text-right tabular-nums text-slate-400">
                    {inv.fraud_score ?? "—"}
                  </td>
                  <td className="px-2 py-2 text-xs text-slate-500">
                    {inv.created_at
                      ? new Date(inv.created_at).toLocaleString()
                      : "—"}
                  </td>
                </tr>
              ))}
              {recent_invoices.length === 0 && (
                <tr>
                  <td colSpan={6} className="py-6 text-center text-slate-500">
                    No invoices yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function statusPill(status: string) {
  const s = status.toLowerCase();
  if (s === "complete") {
    return (
      <span className="pill bg-veridian-500/15 ring-1 ring-veridian-500/40 text-veridian-200">
        complete
      </span>
    );
  }
  if (s === "flagged") {
    return (
      <span className="pill bg-amber-500/15 ring-1 ring-amber-500/35 text-amber-200">
        flagged
      </span>
    );
  }
  if (s === "blocked") {
    return (
      <span className="pill bg-rose-500/15 ring-1 ring-rose-500/35 text-rose-200">
        blocked
      </span>
    );
  }
  return (
    <span className="pill bg-white/5 ring-1 ring-white/10 text-slate-300">
      {status}
    </span>
  );
}

function MetricCard({
  label,
  value,
  sub,
  benchmark,
  tone,
}: {
  label: string;
  value: string;
  sub: string;
  benchmark: string;
  tone: "veridian" | "sky" | "rose" | "amber";
}) {
  const toneClass = {
    veridian: "text-veridian-300",
    sky: "text-sky-400",
    rose: "text-rose-400",
    amber: "text-amber-400",
  }[tone];

  return (
    <div className="card space-y-1 p-4">
      <p className="text-[11px] font-medium uppercase tracking-wide text-slate-400">
        {label}
      </p>
      <p className={`text-3xl font-bold tabular-nums ${toneClass}`}>{value}</p>
      <p className="text-xs text-slate-400">{sub}</p>
      <p className="text-[11px] italic text-slate-600">{benchmark}</p>
    </div>
  );
}

function StatusCard({
  label,
  count,
  tone,
}: {
  label: string;
  count: number;
  tone: "veridian" | "amber" | "rose";
}) {
  const ring = {
    veridian: "ring-veridian-500/35 text-veridian-300",
    amber: "ring-amber-500/35 text-amber-300",
    rose: "ring-rose-500/35 text-rose-300",
  }[tone];

  return (
    <div
      className={`card p-5 text-center ring-1 ${ring} bg-ink-800/80`}
    >
      <p className="text-4xl font-bold tabular-nums">{count}</p>
      <p className="mt-1 text-xs text-slate-400">{label}</p>
    </div>
  );
}
