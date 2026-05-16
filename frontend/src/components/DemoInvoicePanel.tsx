import clsx from "clsx";
import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { fetchDemoInvoicePdf, getDemoInvoices, uploadInvoice } from "../api";
import type { DemoInvoiceMeta, DemoInvoicesCatalog } from "../types";

interface Props {
  /** Same hook-in as `InvoiceUpload`: starts SSE stream after POST returns job id */
  onJobStarted: (jobId: string, file: File) => void;
  /** While pipeline SSE is active — freeze demo picks */
  pipelineBusy: boolean;
  /** While fetching a demo PDF / uploading — freeze dropzone too */
  onDemoBusyChange?: (busy: boolean) => void;
}

export default function DemoInvoicePanel({
  onJobStarted,
  pipelineBusy,
  onDemoBusyChange,
}: Props) {
  const [catalog, setCatalog] = useState<DemoInvoicesCatalog | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [loadingFilename, setLoadingFilename] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getDemoInvoices()
      .then((data) => {
        if (!cancelled) setCatalog(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setCatalogError(
            err instanceof Error ? err.message : "Failed to load demo catalog",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handlePick = useCallback(
    async (meta: DemoInvoiceMeta) => {
      setSubmitError(null);
      setLoadingFilename(meta.filename);
      onDemoBusyChange?.(true);
      try {
        const blob = await fetchDemoInvoicePdf(meta.filename);
        const file = new File([blob], meta.filename, {
          type: "application/pdf",
        });
        const { job_id } = await uploadInvoice(file);
        onJobStarted(job_id, file);
      } catch (err: unknown) {
        const msg =
          err instanceof Error ? err.message : "Could not start demo invoice";
        setSubmitError(msg);
      } finally {
        setLoadingFilename(null);
        onDemoBusyChange?.(false);
      }
    },
    [onDemoBusyChange, onJobStarted],
  );

  const disabledAll = pipelineBusy || loadingFilename !== null;

  function DemoCard({
    meta,
    variant,
  }: {
    meta: DemoInvoiceMeta;
    variant: "clean" | "fraud";
  }) {
    const loading = loadingFilename === meta.filename;
    return (
      <button
        type="button"
        disabled={disabledAll}
        onClick={() => handlePick(meta)}
        className={clsx(
          "relative w-full rounded-xl border-y border-r border-white/10 bg-white/[0.03] py-3 pl-4 pr-4 text-left transition-colors",
          "border-l-[3px]",
          variant === "clean"
            ? "border-l-emerald-500/35"
            : "border-l-amber-500/35",
          !disabledAll && "hover:bg-white/[0.06]",
          disabledAll && !loading && "opacity-45 cursor-not-allowed hover:bg-white/[0.03]",
          loading && "ring-1 ring-veridian-500/50",
        )}
      >
        {loading ? (
          <div className="absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-black/35 backdrop-blur-[1px]">
            <Loader2 className="h-6 w-6 animate-spin text-veridian-200" />
          </div>
        ) : null}
        <div className="font-medium text-white">{meta.label}</div>
        <div className="mt-0.5 text-xs text-slate-400">{meta.vendor}</div>
      </button>
    );
  }

  return (
    <section className="space-y-4">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
          Demo invoices
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          One-click judge scenarios — runs the same pipeline as drag-and-drop.
        </p>
      </div>

      {catalogError ? (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {catalogError}
        </div>
      ) : null}

      {submitError ? (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {submitError}
        </div>
      ) : null}

      {!catalog && !catalogError ? (
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading demo catalog…
        </div>
      ) : null}

      {catalog ? (
        <div className="grid gap-6 md:grid-cols-2">
          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-emerald-400">
              Clean Invoices
            </h3>
            <div className="flex flex-col gap-2">
              {catalog.clean.map((meta) => (
                <DemoCard key={meta.filename} meta={meta} variant="clean" />
              ))}
            </div>
          </div>
          <div className="space-y-3">
            <h3 className="text-sm font-semibold text-amber-400">
              Fraud Scenarios
            </h3>
            <div className="flex flex-col gap-2">
              {catalog.fraud.map((meta) => (
                <DemoCard key={meta.filename} meta={meta} variant="fraud" />
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
