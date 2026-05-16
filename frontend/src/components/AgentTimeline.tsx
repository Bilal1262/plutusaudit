import { useEffect, useMemo, useState } from "react";
import clsx from "clsx";
import {
  AlertTriangle,
  Brain,
  Check,
  Eye,
  FileSearch,
  Loader2,
  MessageSquareText,
  RefreshCcw,
  ScrollText,
  ShieldAlert,
  X,
} from "lucide-react";

import type {
  AgentEvent,
  AgentName,
  AgentStatus,
  PipelineResult,
} from "../types";
import ConfidenceGauge from "./ConfidenceGauge";

const STEP_ORDER: AgentName[] = [
  "doc_intel",
  "accountant",
  "fraud",
  "verifier",
  "explainer",
];

const STEP_META: Record<
  AgentName,
  { label: string; icon: JSX.Element; model: string }
> = {
  doc_intel: {
    label: "Doc Intel",
    icon: <FileSearch className="h-5 w-5" />,
    model: "Gemini 2.5 Flash · multimodal",
  },
  accountant: {
    label: "Accountant",
    icon: <ScrollText className="h-5 w-5" />,
    model: "Gemini 2.5 Flash · HyDE + RAG",
  },
  fraud: {
    label: "Fraud",
    icon: <ShieldAlert className="h-5 w-5" />,
    model: "Featherless Qwen3-32B",
  },
  verifier: {
    label: "Verifier",
    icon: <Eye className="h-5 w-5" />,
    model: "Gemini 2.5 Flash × 3",
  },
  explainer: {
    label: "Explainer",
    icon: <MessageSquareText className="h-5 w-5" />,
    model: "Gemini 2.5 Flash",
  },
  complete: { label: "Done", icon: <Check className="h-5 w-5" />, model: "" },
  error: { label: "Error", icon: <X className="h-5 w-5" />, model: "" },
};

interface Props {
  events: AgentEvent[];
  pipeline?: PipelineResult;
}

type StepState = {
  status: AgentStatus;
  confidence?: number;
  attempt?: number;
  data?: any;
};

function parseEventMs(ts: string | undefined): number | undefined {
  if (!ts) return undefined;
  const ms = Date.parse(ts);
  return Number.isNaN(ms) ? undefined : ms;
}

/** Wall-clock ticker while any step is actively running — drives elapsed badges. */
function useNowTicker(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), 400);
    return () => window.clearInterval(id);
  }, [active]);
  return now;
}

function stepTimingSeconds(
  events: AgentEvent[],
  step: AgentName,
  stateStatus: AgentStatus,
  nowMs: number,
): { runningElapsedSec?: number; doneSec?: number } {
  const mine = events.filter((e) => e.agent === step);
  if (!mine.length) return {};

  let lastRunStartMs: number | undefined;
  let lastDoneDurSec: number | undefined;

  for (const ev of mine) {
    const ts = parseEventMs(ev.timestamp);
    if (ev.status === "running" || ev.status === "retrying") {
      lastRunStartMs = ts ?? lastRunStartMs;
      continue;
    }
    if (ev.status === "complete" || ev.status === "failed") {
      if (ts !== undefined && lastRunStartMs !== undefined) {
        lastDoneDurSec = Math.max(
          lastDoneDurSec ?? 0,
          Math.max(0, (ts - lastRunStartMs) / 1000),
        );
      }
      lastRunStartMs = undefined;
    }
  }

  if (stateStatus === "running" || stateStatus === "retrying") {
    if (lastRunStartMs !== undefined) {
      return {
        runningElapsedSec: Math.max(
          0,
          Math.floor((nowMs - lastRunStartMs) / 1000),
        ),
      };
    }
  }

  if (stateStatus === "complete" || stateStatus === "failed") {
    if (lastDoneDurSec !== undefined) {
      return { doneSec: Math.round(lastDoneDurSec * 10) / 10 };
    }
  }

  return {};
}

function pipelineWallClock(
  events: AgentEvent[],
): { totalSeconds?: number } {
  const startMs = parseEventMs(
    events.find(
      (e) => e.agent === "doc_intel" && e.status === "running",
    )?.timestamp,
  );

  let endCandidate: AgentEvent | undefined;
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.agent === "complete" && e.status === "complete") {
      endCandidate = e;
      break;
    }
  }

  const endMs = parseEventMs(endCandidate?.timestamp);
  if (
    startMs === undefined ||
    endMs === undefined ||
    endMs < startMs
  ) {
    return {};
  }
  return {
    totalSeconds: Math.round(((endMs - startMs) / 1000) * 10) / 10,
  };
}

function statusFromEvents(events: AgentEvent[], step: AgentName): StepState {
  const matching = events.filter((e) => e.agent === step);
  if (matching.length === 0) return { status: "waiting" };
  const last = matching[matching.length - 1];
  return {
    status: last.status,
    confidence: last.confidence,
    attempt: last.attempt,
    data: last.data,
  };
}

function StepCircle({
  state,
  step,
  expanded,
  onClick,
  runningElapsedSec,
  doneSec,
}: {
  state: StepState;
  step: AgentName;
  expanded: boolean;
  onClick: () => void;
  runningElapsedSec?: number;
  doneSec?: number;
}) {
  const meta = STEP_META[step];

  const ring = {
    waiting: "ring-white/10 bg-white/5 text-slate-400",
    running: "ring-veridian-500/60 bg-veridian-600/15 text-veridian-200",
    retrying: "ring-amber-500/60 bg-amber-600/15 text-amber-200",
    complete:
      "ring-veridian-500/60 bg-veridian-600/25 text-veridian-200 shadow-glow",
    failed: "ring-rose-500/60 bg-rose-600/20 text-rose-200",
  }[state.status];

  const icon =
    state.status === "running" ? (
      <Loader2 className="h-5 w-5 animate-spin" />
    ) : state.status === "retrying" ? (
      <RefreshCcw className="h-5 w-5 animate-spin" />
    ) : state.status === "complete" ? (
      <Check className="h-5 w-5" />
    ) : state.status === "failed" ? (
      <X className="h-5 w-5" />
    ) : (
      meta.icon
    );

  return (
    <button
      onClick={onClick}
      className={clsx(
        "flex flex-col items-center group focus:outline-none",
        state.status === "waiting" && "cursor-default",
      )}
      disabled={state.status === "waiting"}
    >
      <div
        className={clsx(
          "grid h-14 w-14 place-items-center rounded-full ring-2 transition-all",
          ring,
          expanded && "scale-110",
        )}
      >
        {icon}
      </div>
      <div className="mt-2 text-xs font-medium text-slate-200">
        {meta.label}
      </div>
      {state.confidence !== undefined && (
        <div className="mt-0.5 text-[11px] text-slate-400">
          {Math.round(state.confidence * 100)}%
        </div>
      )}
      {state.attempt && state.attempt > 1 && (
        <span className="pill mt-1 bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/40">
          Attempt {state.attempt}
        </span>
      )}
      {(state.status === "running" || state.status === "retrying") &&
        runningElapsedSec !== undefined && (
          <span className="mt-1 animate-pulse text-[10px] text-slate-500">
            {runningElapsedSec}s elapsed…
          </span>
        )}
      {(state.status === "complete" || state.status === "failed") &&
        doneSec !== undefined && (
          <span className="mt-0.5 block text-[10px] tabular-nums text-slate-500">
            {doneSec}s
          </span>
        )}
    </button>
  );
}

function Connector({
  left,
  right,
}: {
  left: StepState;
  right: StepState;
}) {
  const filled =
    left.status === "complete" &&
    (right.status === "complete" ||
      right.status === "running" ||
      right.status === "retrying" ||
      right.status === "failed");
  return (
    <div className="relative flex-1 mx-2 h-1">
      <div className="absolute inset-0 rounded bg-white/10" />
      <div
        className={clsx(
          "absolute inset-y-0 left-0 rounded transition-all duration-700",
          filled ? "w-full bg-veridian-500/80" : "w-0 bg-veridian-500/80",
        )}
      />
    </div>
  );
}

function VerifierBreakdown({ data }: { data: any }) {
  const votes: any[] = data?.votes || data?.verifier_votes || [];
  if (!votes.length)
    return <p className="text-sm text-slate-400">No verifier results yet.</p>;
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
      {votes.map((v: any) => (
        <div
          key={v.verifier}
          className={clsx(
            "rounded-xl p-3 ring-1",
            v.passed
              ? "bg-veridian-500/10 ring-veridian-500/40 text-veridian-100"
              : "bg-rose-500/10 ring-rose-500/40 text-rose-100",
          )}
        >
          <div className="flex items-center justify-between">
            <div className="text-sm font-semibold capitalize">
              V{v.verifier === "numerical" ? 1 : v.verifier === "citation" ? 2 : 3}{" "}
              · {v.verifier}
            </div>
            {v.passed ? (
              <Check className="h-4 w-4" />
            ) : (
              <AlertTriangle className="h-4 w-4" />
            )}
          </div>
          {v.violations && v.violations.length > 0 && (
            <ul className="mt-2 list-disc list-inside text-xs space-y-0.5">
              {v.violations.slice(0, 3).map((vi: string, i: number) => (
                <li key={i}>{vi}</li>
              ))}
            </ul>
          )}
          {v.evidence && (
            <div className="mt-2 text-[11px] italic opacity-80">
              "{String(v.evidence).slice(0, 120)}"
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function ExpandedPanel({
  step,
  state,
  pipeline,
}: {
  step: AgentName;
  state: StepState;
  pipeline?: PipelineResult;
}) {
  const meta = STEP_META[step];
  // Prefer the rich pipeline result if available; otherwise SSE event data.
  const data =
    step === "doc_intel"
      ? pipeline?.extraction ?? state.data
      : step === "accountant"
        ? pipeline?.accountant ?? state.data
        : step === "fraud"
          ? pipeline?.fraud ?? state.data
          : step === "verifier"
            ? pipeline?.verifier ?? state.data
            : step === "explainer"
              ? pipeline?.explanation ?? state.data
              : state.data;

  const reasoning =
    (data as any)?.reasoning ??
    (data as any)?.llm_result?.reasoning ??
    (data as any)?.rationale;

  return (
    <div className="card mt-6 p-5">
      <div className="flex items-start gap-4">
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-white/5 ring-1 ring-white/10 text-veridian-300">
          {meta.icon}
        </div>
        <div className="flex-1">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm font-semibold text-white">
                {meta.label}
              </div>
              <div className="text-[11px] text-slate-400">{meta.model}</div>
            </div>
            {typeof state.confidence === "number" && (
              <ConfidenceGauge value={state.confidence} size={110} />
            )}
          </div>

          {/* Step-specific summary */}
          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            {step === "doc_intel" && data && (
              <>
                <Kv k="Vendor" v={(data as any).vendor_name} />
                <Kv k="Invoice #" v={(data as any).invoice_number} />
                <Kv
                  k="Grand total"
                  v={
                    (data as any).grand_total != null
                      ? `${(data as any).currency || ""} ${(data as any).grand_total}`
                      : null
                  }
                />
                <Kv k="Invoice date" v={(data as any).invoice_date} />
                <Kv k="PO number" v={(data as any).po_number ?? "—"} />
                {Array.isArray((data as any).extraction_warnings) &&
                  (data as any).extraction_warnings.length > 0 && (
                    <div className="md:col-span-2 text-xs text-amber-300">
                      ⚠ Warnings:{" "}
                      {(data as any).extraction_warnings.join("; ")}
                    </div>
                  )}
              </>
            )}
            {step === "accountant" && data && (
              <>
                <Kv k="DR" v={(data as any).gl_account_debit} />
                <Kv k="CR" v={(data as any).gl_account_credit} />
                <Kv k="Standard" v={(data as any).standard_cited} />
                <Kv k="Paragraph" v={(data as any).paragraph_cited} />
                <Kv
                  k="Deferral"
                  v={(data as any).deferral_required ? "yes" : "no"}
                />
                <Kv
                  k="Human review"
                  v={(data as any).requires_human_review ? "yes" : "no"}
                />
              </>
            )}
            {step === "fraud" && data && (
              <>
                <Kv k="Risk score" v={(data as any).risk_score} />
                <Kv k="Tier" v={(data as any).tier} />
                <Kv
                  k="Top signals"
                  v={
                    ((data as any).llm_result?.top_3_signals || []).join(", ") ||
                    "—"
                  }
                />
                <Kv
                  k="Action"
                  v={(data as any).llm_result?.recommended_action ?? "—"}
                />
              </>
            )}
            {step === "verifier" && (
              <div className="md:col-span-2">
                <VerifierBreakdown data={data} />
                {(data as any)?.critique && (
                  <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-100">
                    <div className="font-semibold mb-1">
                      Retry critique sent back to Accountant
                    </div>
                    <div className="mono whitespace-pre-wrap text-[11px]">
                      {(data as any).critique}
                    </div>
                  </div>
                )}
              </div>
            )}
            {step === "explainer" && data && (
              <div className="md:col-span-2">
                <div className="text-sm font-semibold text-white">
                  {(data as any).headline}
                </div>
                <p className="mt-1 text-sm text-slate-300">
                  {(data as any).rationale}
                </p>
                <p className="mt-2 text-xs text-slate-400">
                  {(data as any).confidence_statement}
                </p>
              </div>
            )}
          </div>

          {reasoning && (
            <details className="mt-4">
              <summary className="cursor-pointer text-xs uppercase tracking-wider text-slate-400 hover:text-veridian-300">
                Decision rationale
              </summary>
              <pre className="mono mt-2 whitespace-pre-wrap rounded-lg bg-black/40 p-3 text-[12px] text-slate-300">
                {String(reasoning)}
              </pre>
            </details>
          )}
        </div>
      </div>
    </div>
  );
}

function Kv({ k, v }: { k: string; v: any }) {
  return (
    <div className="rounded-lg bg-white/5 p-2.5">
      <div className="text-[11px] uppercase tracking-wider text-slate-400">
        {k}
      </div>
      <div className="mt-0.5 text-sm text-white break-words">
        {v === null || v === undefined || v === "" ? "—" : String(v)}
      </div>
    </div>
  );
}

export default function AgentTimeline({ events, pipeline }: Props) {
  const stepStates = useMemo(() => {
    return STEP_ORDER.map((s) => statusFromEvents(events, s));
  }, [events]);

  const runningTicker = useMemo(
    () => stepStates.some((s) => ["running", "retrying"].includes(s.status)),
    [stepStates],
  );
  const nowMs = useNowTicker(runningTicker);

  const pipelineTotals = useMemo(() => pipelineWallClock(events), [events]);
  const pipelineTerminal = useMemo(
    () => events.some((e) => e.agent === "complete" && e.status === "complete"),
    [events],
  );
  const auditEntryCount = pipeline?.audit_entries?.length ?? 0;

  const [expanded, setExpanded] = useState<AgentName | null>(null);

  const stepFlags = stepStates.map((s) => s.status);
  // Auto-expand whichever step is currently running, unless user clicked.
  const runningStep = STEP_ORDER.find((_, i) =>
    ["running", "retrying"].includes(stepFlags[i]),
  );
  let lastCompleteStep: AgentName | null = null;
  for (let i = STEP_ORDER.length - 1; i >= 0; i--) {
    if (stepFlags[i] === "complete") {
      lastCompleteStep = STEP_ORDER[i];
      break;
    }
  }
  const autoExpanded = expanded ?? runningStep ?? lastCompleteStep;

  return (
    <section className="card p-6">
      <div className="flex items-center gap-2 text-sm text-slate-300">
        <Brain className="h-4 w-4 text-veridian-300" />
        <span className="font-semibold text-white">Control Workflow</span>
        <span className="text-slate-500">·</span>
        <span className="text-slate-400">
          real-time processing with hash-chained evidence capture
        </span>
      </div>

      {pipelineTerminal && pipelineTotals.totalSeconds != null && (
        <div className="mt-3 text-xs text-veridian-300">
          <span className="mr-1 text-veridian-400">✓</span>
          Complete in{" "}
          <span className="font-semibold tabular-nums text-veridian-200">
            {pipelineTotals.totalSeconds}s
          </span>
          {" — "}
          audit trail written (
          <span className="tabular-nums font-medium text-veridian-200">
            {auditEntryCount}
          </span>{" "}
          entries)
        </div>
      )}

      <div className="mt-6 flex items-center justify-between">
        {STEP_ORDER.map((step, i) => {
          const t = stepTimingSeconds(
            events,
            step,
            stepStates[i].status,
            nowMs,
          );
          return (
            <div key={step} className="flex items-center flex-1 last:flex-none">
              <StepCircle
                step={step}
                state={stepStates[i]}
                expanded={autoExpanded === step}
                onClick={() =>
                  setExpanded(autoExpanded === step ? null : step)
                }
                runningElapsedSec={t.runningElapsedSec}
                doneSec={t.doneSec}
              />
              {i < STEP_ORDER.length - 1 && (
                <Connector left={stepStates[i]} right={stepStates[i + 1]} />
              )}
            </div>
          );
        })}
      </div>

      {autoExpanded && (
        <ExpandedPanel
          step={autoExpanded}
          state={stepStates[STEP_ORDER.indexOf(autoExpanded)]}
          pipeline={pipeline}
        />
      )}
    </section>
  );
}
