import { useState } from "react";
import { Sparkles } from "lucide-react";

import AgentTimeline from "../components/AgentTimeline";
import DemoInvoicePanel from "../components/DemoInvoicePanel";
import FraudHeatmap from "../components/FraudHeatmap";
import InvoiceUpload from "../components/InvoiceUpload";
import JournalEntryCard from "../components/JournalEntryCard";
import ReviewQueue from "../components/ReviewQueue";
import VendorApprovalPrompt from "../components/VendorApprovalPrompt";
import { usePipeline } from "../context/PipelineContext";

export default function Dashboard() {
  const [demoBusy, setDemoBusy] = useState(false);
  const {
    events,
    pipeline,
    jobId,
    streamDone,
    attachPipelineStream,
    vendorPromptDismissedJobId,
    dismissVendorBanner,
    activeFilename,
  } = usePipeline();

  function handleJobStarted(id: string, file: File) {
    attachPipelineStream(id, file.name);
  }

  const pipelineBusy = !!jobId && !streamDone;

  const verdict = pipeline.verdict || pipeline.verifier?.verdict;
  const hasResult = !!pipeline.extraction;

  const rawVendor = pipeline.extraction?.vendor_name?.trim();
  const showVendorApproval =
    streamDone &&
    !!jobId &&
    vendorPromptDismissedJobId !== jobId &&
    pipeline.fraud?.signals?.new_vendor === true &&
    !!rawVendor;

  return (
    <div className="space-y-8">
      <section className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            PlutusAudit AI Control Desk
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">
            Process supplier invoices through an auditable control workflow:
            document intelligence, accounting classification, fraud review,
            independent verification, and executive-ready explanation. Every
            decision is written to a tamper-evident audit chain.
          </p>
          <details className="mt-4 max-w-2xl rounded-xl border border-white/10 bg-white/[0.02] px-4 py-3 text-sm">
            <summary className="cursor-pointer select-none text-veridian-200">
              How vendor approval works (demo walkthrough)
            </summary>
            <pre className="mt-3 whitespace-pre-wrap mono text-[11px] leading-relaxed text-slate-400">
              {`Judge uploads invoice
        ↓
System processes it
        ↓
New vendor detected → fraud score includes new_vendor signal (e.g. ~30 pts in many demos)
        ↓
After results: “Is this vendor approved?” banner
        [✓ Approve vendor]   [✗ Keep flagged]
        ↓
Judge clicks Approve → vendor master updated in Postgres
        ↓
Next upload → normalized vendor key matches approved row → new_vendor signal clears`}
            </pre>
          </details>
        </div>
        <div className="flex items-center gap-2">
          <span className="pill bg-veridian-500/10 text-veridian-200 ring-1 ring-veridian-500/40">
            <Sparkles className="h-3 w-3" />
            Operational
          </span>
          {verdict && (
            <span
              className={`pill ring-1 uppercase tracking-wider ${
                verdict === "APPROVED"
                  ? "bg-veridian-500/15 ring-veridian-500/40 text-veridian-200"
                  : verdict === "BLOCKED"
                    ? "bg-rose-500/15 ring-rose-500/40 text-rose-200"
                    : "bg-amber-500/15 ring-amber-500/40 text-amber-200"
              }`}
            >
              {verdict}
            </span>
          )}
        </div>
      </section>

      <DemoInvoicePanel
        onJobStarted={handleJobStarted}
        pipelineBusy={pipelineBusy}
        onDemoBusyChange={setDemoBusy}
      />

      <InvoiceUpload
        onJobStarted={handleJobStarted}
        disabled={pipelineBusy || demoBusy}
      />

      {(jobId || hasResult) && (
        <AgentTimeline events={events} pipeline={pipeline} />
      )}

      {pipeline.accountant && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <JournalEntryCard
            accountant={pipeline.accountant}
            currency={pipeline.extraction?.currency}
          />
          {pipeline.fraud && <FraudHeatmap fraud={pipeline.fraud} />}
        </div>
      )}

      {!pipeline.accountant && pipeline.fraud && (
        <FraudHeatmap fraud={pipeline.fraud} />
      )}

      {streamDone && showVendorApproval && rawVendor ? (
        <VendorApprovalPrompt
          vendorName={rawVendor}
          onClose={dismissVendorBanner}
        />
      ) : null}

      {pipeline.explanation && (
        <section className="card p-6">
          <div className="text-sm font-semibold text-white">
            {pipeline.explanation.headline}
          </div>
          <p className="mt-2 text-sm leading-relaxed text-slate-300">
            {pipeline.explanation.rationale}
          </p>
          <p className="mt-2 text-xs text-slate-400">
            {pipeline.explanation.confidence_statement}
          </p>
          {activeFilename ? (
            <div className="mt-3 text-[11px] text-slate-500">
              File: <span className="mono">{activeFilename}</span> · job{" "}
              <span className="mono">{jobId?.slice(0, 8)}…</span>
            </div>
          ) : null}
        </section>
      )}

      <ReviewQueue />
    </div>
  );
}
