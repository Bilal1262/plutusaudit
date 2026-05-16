import axios from "axios";
import type {
  AgentEvent,
  AnalyticsPayload,
  AuditEntry,
  ChainVerifyResult,
  DemoInvoiceMeta,
  DemoInvoicesCatalog,
  Invoice,
  PipelineResult,
  Vendor,
} from "./types";

// In dev, vite proxies /api -> backend. In production (Nginx), the same is true.
// VITE_API_BASE can override (e.g. VITE_API_BASE=http://localhost:8000 for raw mode).
export const API_BASE = (
  (import.meta as any).env?.VITE_API_BASE || "/api"
).replace(/\/+$/, "");

/** Origin for raw `fetch`. Empty = browser default (paths like `/api/...` use the proxy). */
export const API = (
  (import.meta as any).env?.VITE_API_ORIGIN ?? ""
).replace(/\/+$/, "");

const http = axios.create({
  baseURL: API_BASE,
  timeout: 60_000,
});

// ── REST ──────────────────────────────────────────────────────────────────────
export async function uploadInvoice(
  file: File,
): Promise<{ job_id: string; status: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const { data } = await http.post("/process-invoice", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function getInvoiceHistory(
  page = 1,
  page_size = 50,
): Promise<Invoice[]> {
  const { data } = await http.get("/invoices", {
    params: { page, page_size },
  });
  return data.items;
}

export async function getInvoice(id: string): Promise<PipelineResult & Invoice> {
  const { data } = await http.get(`/invoices/${id}`);
  return data;
}

export async function getAuditLog(
  page = 1,
  page_size = 50,
): Promise<{ items: AuditEntry[]; total: number }> {
  const { data } = await http.get("/audit-log", {
    params: { page, page_size },
  });
  return data;
}

export async function verifyAuditChain(): Promise<ChainVerifyResult> {
  const { data } = await http.get("/audit-log/verify");
  return data;
}

export async function submitOverride(
  entryId: string,
  reason: string,
  newClassification?: string,
): Promise<{ ok: boolean; new_entry_id: string; new_sequence: number }> {
  const { data } = await http.post(`/audit-log/${entryId}/override`, {
    reason,
    new_classification: newClassification ?? null,
  });
  return data;
}

export async function getVendors(): Promise<Vendor[]> {
  const { data } = await http.get("/vendors");
  return data;
}

export async function approveVendor(
  vendorName: string,
  approvedBy = "user",
): Promise<{ status: string; vendor: string }> {
  const { data } = await http.post("/vendors/approve", {
    vendor_name: vendorName,
    approved_by: approvedBy,
  });
  return data;
}

export async function removeVendor(vendorId: string): Promise<void> {
  await http.delete(`/vendors/${vendorId}`);
}

export async function getHealth(): Promise<{
  status: string;
  rag_loaded: boolean;
  db_connected: boolean;
  env: string;
  version: string;
}> {
  const { data } = await http.get("/health");
  return data;
}

export async function getAnalytics(): Promise<AnalyticsPayload> {
  const { data } = await http.get("/analytics");
  return data;
}

function _normalizeDemoRow(
  row: Record<string, unknown>,
  index: number,
): DemoInvoiceMeta {
  const filename = String(row.filename ?? "");
  const slug = filename
    .replace(/[^a-zA-Z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return {
    id: String(row.id ?? (slug || `demo_${index}`)),
    filename,
    label: String(row.label ?? ""),
    vendor: String(row.vendor ?? ""),
    amount: String(row.amount ?? ""),
    expected: String(row.expected ?? row.expected_outcome ?? ""),
    description: String(row.description ?? ""),
  };
}

export async function getDemoInvoices(): Promise<DemoInvoicesCatalog> {
  const resp = await fetch(`${API}/api/demo-invoices`);
  if (!resp.ok) {
    const t = await resp.text();
    throw new Error(t || `HTTP ${resp.status}`);
  }
  const raw = (await resp.json()) as {
    clean?: Record<string, unknown>[];
    fraud?: Record<string, unknown>[];
  };
  return {
    clean: (raw.clean ?? []).map(_normalizeDemoRow),
    fraud: (raw.fraud ?? []).map(_normalizeDemoRow),
  };
}

export async function fetchDemoInvoicePdf(filename: string): Promise<File> {
  const resp = await fetch(
    `${API}/api/demo-invoices/${encodeURIComponent(filename)}`,
  );
  if (!resp.ok) {
    const t = await resp.text();
    throw new Error(t || `HTTP ${resp.status}`);
  }
  const blob = await resp.blob();
  return new File([blob], filename, { type: "application/pdf" });
}

// ── SSE stream of agent events ────────────────────────────────────────────────
export function streamProcessing(
  jobId: string,
  onUpdate: (e: AgentEvent) => void,
  onEnd?: () => void,
  onError?: (err: any) => void,
): EventSource {
  const url = `${API_BASE}/stream/${jobId}`;
  const src = new EventSource(url);

  src.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data) as AgentEvent;
      onUpdate(data);
    } catch (err) {
      console.warn("SSE parse error", err, msg.data);
    }
  };
  src.addEventListener("end", () => {
    src.close();
    onEnd?.();
  });
  src.onerror = (err) => {
    src.close();
    onError?.(err);
    onEnd?.();
  };
  return src;
}

// ── Demo: tamper helper (dev-only backend endpoint) ───────────────────────────
export async function demoTamper(entryId: string): Promise<{ ok: boolean }> {
  const { data } = await http.post(`/_demo/tamper/${entryId}`);
  return data;
}
