// ── Agent pipeline ────────────────────────────────────────────────────────────
export type AgentName =
  | "doc_intel"
  | "accountant"
  | "fraud"
  | "verifier"
  | "explainer"
  | "complete"
  | "error";

export type AgentStatus =
  | "waiting"
  | "running"
  | "complete"
  | "failed"
  | "retrying";

export interface AgentEvent {
  agent: AgentName;
  status: AgentStatus;
  confidence?: number;
  attempt?: number;
  data?: any;
  timestamp?: string;
}

// ── Doc Intel ─────────────────────────────────────────────────────────────────
export interface InvoiceExtraction {
  reasoning?: string;
  vendor_name: string | null;
  vendor_address?: string | null;
  vendor_tax_id?: string | null;
  invoice_number: string | null;
  invoice_date?: string | null;
  due_date?: string | null;
  po_number?: string | null;
  currency: string;
  subtotal?: number | null;
  tax_amount?: number | null;
  grand_total: number | null;
  line_items: LineItem[];
  payment_terms?: string | null;
  bank_account_change_requested?: boolean;
  received_at?: string | null;
  extraction_warnings?: string[];
  extraction_confidence?: number;
  requires_human_review?: boolean;
}

export interface LineItem {
  description: string;
  quantity?: number;
  unit_price?: number;
  line_total?: number;
}

// ── Accountant ────────────────────────────────────────────────────────────────
export interface AccountantResult {
  reasoning?: string;
  gl_account_debit: string;
  gl_account_credit: string;
  amount: number;
  standard_cited: string;
  paragraph_cited: string;
  deferral_required?: boolean;
  amortization_schedule?: any;
  confidence: number;
  requires_human_review?: boolean;
  retrieved_chunk_ids?: string[];
  retrieved_chunks?: RetrievedChunk[];
  guard_warnings?: string[];
}

export interface RetrievedChunk {
  id: string;
  standard: string;
  paragraph: string;
  topic: string;
  rule: string;
  keywords?: string;
  rank?: number;
  dense_score?: number;
  bm25_score?: number;
}

// ── Fraud ─────────────────────────────────────────────────────────────────────
export interface FraudSignals {
  exact_duplicate: boolean;
  near_duplicate_count: number;
  benford_flag: boolean;
  benford_mad: number | null;
  round_number: boolean;
  below_threshold: boolean;
  missing_po: boolean;
  vague_description: boolean;
  new_vendor: boolean;
  off_hours_submission: boolean;
  bank_account_change_requested?: boolean;
  vendor_history_count?: number;
  /** Repeated sub-threshold invoices from same vendor near an approval band */
  invoice_splitting_sequence?: boolean;
}

export interface FraudLLMResult {
  reasoning?: string;
  risk_score: number;
  tier: "clean" | "review" | "block";
  top_3_signals?: string[];
  plain_english_explanation?: string;
  recommended_action?: string;
  source?: string;
}

export interface FraudResult {
  signals: FraudSignals;
  llm_result: FraudLLMResult;
  risk_score: number;
  tier: "clean" | "review" | "block";
  evaluated_at?: string;
}

// ── Verifier ──────────────────────────────────────────────────────────────────
export interface VerifierVote {
  verifier: "numerical" | "citation" | "schema";
  passed: boolean;
  delta?: number;
  evidence?: string;
  violations: string[];
  confidence: number;
  source?: string;
}

export interface VerifierResult {
  verdict: "APPROVED" | "APPROVED_WITH_WARNING" | "ESCALATED";
  final_confidence: number;
  passed_count: number;
  verifier_votes: VerifierVote[];
  history?: any[];
  attempt: number;
  critique?: string | null;
}

// ── Explainer ─────────────────────────────────────────────────────────────────
export interface Explanation {
  headline: string;
  rationale: string;
  confidence_statement: string;
  override_invitation?: string;
  full_text?: string;
  source?: string;
}

// ── Pipeline ──────────────────────────────────────────────────────────────────
export interface PipelineResult {
  job_id: string;
  filename: string;
  size: number;
  invoice_id?: string;
  extraction?: InvoiceExtraction;
  accountant?: AccountantResult;
  fraud?: FraudResult;
  verifier?: VerifierResult;
  verdict?: string;
  final_confidence?: number;
  explanation?: Explanation;
  audit_entries?: AuditEntrySummary[];
}

export interface AuditEntrySummary {
  agent: string;
  entry_id: string;
  sequence: number;
  entry_hash: string;
}

// ── Invoices list ─────────────────────────────────────────────────────────────
export interface Invoice {
  id: string;
  filename: string;
  upload_timestamp: string | null;
  vendor_name: string | null;
  invoice_number: string | null;
  grand_total: number | null;
  currency: string;
  status: string;
  fraud_tier: string | null;
  fraud_score: number | null;
  processing_time_ms: number | null;
}

// ── Audit log ─────────────────────────────────────────────────────────────────
export interface AuditEntry {
  entry_id: string;
  sequence: number;
  prev_hash: string;
  entry_hash: string;
  timestamp: string;
  agent_name: string;
  agent_version: string;
  model_name: string;
  input_hash: string;
  output: any;
  confidence: number | null;
  citations: string[];
  reasoning: string | null;
  verifier_votes: VerifierVote[];
  user_id: string;
  human_override: string | null;
  invoice_id: string | null;
}

export interface ChainVerifyResult {
  valid: boolean;
  count?: number;
  broken_at_sequence?: number;
  reason?: string;
  expected_prev_hash?: string;
  found_prev_hash?: string;
  expected_entry_hash?: string;
  found_entry_hash?: string;
}

// ── Analytics ───────────────────────────────────────────────────────────────────
export interface AnalyticsSummary {
  total_processed: number;
  approved: number;
  flagged: number;
  blocked: number;
  /** Invoices that required intervention (flagged + blocked) */
  fraud_surfaced: number;
  touchless_rate: number;
  avg_processing_seconds: number;
  fraud_value_caught: number;
  cost_saved: number;
}

export interface AnalyticsGlRow {
  account: string;
  amount: number;
}

export interface AnalyticsRecentInvoice {
  filename: string;
  vendor: string | null;
  amount: number;
  currency: string;
  status: string;
  fraud_score: number | null;
  created_at: string | null;
}

export interface AnalyticsPayload {
  summary: AnalyticsSummary;
  gl_breakdown: AnalyticsGlRow[];
  recent_invoices: AnalyticsRecentInvoice[];
}

// ── Vendor ────────────────────────────────────────────────────────────────────
export interface Vendor {
  id: string;
  name: string;
  is_approved: boolean;
  invoice_count: number;
  created_at: string | null;
}

// ── Demo invoices (bundled PDFs for judges) ───────────────────────────────────
export interface DemoInvoiceMeta {
  id: string;
  filename: string;
  label: string;
  vendor: string;
  amount: string;
  expected: string;
  description: string;
}

export interface DemoInvoicesCatalog {
  clean: DemoInvoiceMeta[];
  fraud: DemoInvoiceMeta[];
}
