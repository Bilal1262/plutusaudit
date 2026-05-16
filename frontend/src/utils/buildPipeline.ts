import type { AgentEvent, PipelineResult } from "../types";

export function buildPipelineFromEvents(events: AgentEvent[]): PipelineResult {
  const p: PipelineResult = {
    job_id: "",
    filename: "",
    size: 0,
  };
  for (const e of events) {
    if (e.agent === "doc_intel" && e.status === "complete") {
      p.extraction = e.data;
    } else if (e.agent === "accountant" && e.status === "complete") {
      p.accountant = e.data;
    } else if (e.agent === "fraud" && e.status === "complete") {
      p.fraud = e.data;
    } else if (e.agent === "verifier" && e.status === "complete") {
      p.verifier = e.data;
      if (e.data?.accountant_output) {
        p.accountant = e.data.accountant_output;
      }
    } else if (e.agent === "verifier" && e.status === "failed") {
      p.verifier = e.data;
      if (e.data?.accountant_output) {
        p.accountant = e.data.accountant_output;
      }
    } else if (e.agent === "explainer" && e.status === "complete") {
      p.explanation = e.data;
    } else if (e.agent === "complete") {
      p.invoice_id = e.data?.invoice_id;
      p.verdict = e.data?.verdict;
      p.audit_entries = e.data?.audit_entries;
    }
  }
  return p;
}
