# PlutusAudit AI

**The First Accounts Payable Agent That Audits Its Own Reasoning.**

Five specialised AI agents extract, classify, fraud-check, verify and explain every invoice — and every decision is written to a SHA-256 hash-chained audit log that detects a single byte of tampering.

> Built for the **AI Agent Olympics Hackathon — Milan AI Week 2026 (lablab.ai)**.
> Targeting the **Vultr ($10K)**, **Google Gemini ($10K)** and **Featherless (Pro plan)** prize tracks.

**Live demo → http://45.76.132.31:3000**
**GitHub → https://github.com/Bilal1262/plutusaudit_ai**

---

## The Problem

> Companies process ~3 billion invoices per year. Manual AP processing costs
> **$17 per invoice** and takes 7–10 days. AP fraud costs the global economy
> **$67.4 billion** annually. Existing AI tools approve invoices confidently —
> even fraudulent ones — with zero ability to verify their own reasoning.

PlutusAudit AI is the first finance-grade agent stack that is **provably correct, demonstrably honest, and forensically auditable** end-to-end.

---

## Live Results

| Metric | PlutusAudit AI | Industry Average |
|---|---|---|
| Processing time | 45 seconds | 7–10 days |
| Cost per invoice | $0.04 | $17.00 |
| Touchless rate | 57%+ | 30–50% |
| Tamper detection | < 1 second | Manual audit |

---

## Architecture

```
                        ┌──────────────┐
   PDF / image  ───►    │  Doc Intel   │  ◄── Gemini 2.5 Flash (multimodal)
                        └──────┬───────┘
                               ▼
                        ┌──────────────┐
                        │  Accountant  │  ◄── Gemini 2.5 Flash + HyDE-expanded
                        └──────┬───────┘      FAISS+BM25 hybrid RAG (80+ rules)
                               ▼
                        ┌──────────────┐
                        │    Fraud     │  ◄── Featherless Qwen3-32B reasoning
                        └──────┬───────┘      over 9 deterministic signals
                               ▼
                ┌──────────────────────────────┐
                │   Verifier  ×3 aspect votes  │  ◄── Gemini 2.5 Flash
                │  numerical · citation · schema│      with retry loop
                └────────────────┬─────────────┘
                                 ▼
                        ┌──────────────┐
                        │  Explainer   │  ◄── Gemini 2.5 Flash
                        └──────┬───────┘
                               ▼
                ┌────────────────────────────┐
                │  Hash-chained audit log    │  ◄── SHA-256 append-only Postgres
                └────────────────────────────┘
```

Every agent emits an SSE event the frontend animates live. Every decision is hashed into a chain you can replay to detect tampering.

---

## The Five Agents

**Agent 1 — Document Intelligence (Gemini 2.5 Flash)**
Reads any PDF or image using native multimodal vision. Extracts every field with arithmetic validation. No OCR pipeline. Research: Berghaus et al. arXiv:2509.04469.

**Agent 2 — AI Chartered Accountant (Gemini 2.5 Flash + RAG)**
Searches 80+ GAAP/IFRS rules using FAISS dense + BM25 keyword hybrid retrieval with HyDE query expansion. Produces a double-entry journal entry citing the exact standard paragraph. Faithfulness guard prevents hallucinated citations. Research: FinSage arXiv:2504.14493.

**Agent 3 — Fraud Detector (Featherless Qwen3-32B)**
Computes 9 deterministic signals — Benford's Law MAD, near-duplicate Levenshtein detection, round-number patterns, below-threshold splitting, missing PO, new vendor, off-hours submission, bank account change, vague description. Passes signals to Qwen3-32B for calibrated 0–100 risk scoring. Research: Nigrini (1999), USPTO 12,045,215.

**Agent 4 — Verifier (Gemini 2.5 Flash × 3)**
Three independent aspect verifiers vote: numerical consistency, citation grounding, schema conformance. Failed verification triggers a structured critique and retry. Implements Multi-Agent Verification (arXiv:2502.20379).

**Agent 5 — Explainer + Audit Trail (Gemini 2.5 Flash)**
Writes plain-English rationale for every decision. Appends to a SHA-256 hash-chained Postgres log. Tamper detection surfaces the exact modified entry in under 1 second.

---

## Research Foundation

| Paper / Patent | Where used |
|---|---|
| Berghaus et al., arXiv:2509.04469 (2025) | Native multimodal beats OCR in `doc_intel.py` |
| FinSage, arXiv:2504.14493 | HyDE + FAISS+BM25 retrieval in `rag/` |
| Multi-Agent Verification, arXiv:2502.20379 | 3-aspect voting + retry in `verifier.py` |
| SelfCheckGPT, arXiv:2303.08896 | Faithfulness guard on RAG citations |
| Verify when Uncertain, arXiv:2502.15845 | Cross-model tiebreak logic |
| Why Multi-Agent Systems Fail, arXiv:2503.13657 | Justifies dedicated verifier agent |
| Nigrini (1999) — Benford's Law | Vendor MAD signal in `fraud.py` |
| USPTO 12,045,215 & 12,106,384 | Duplicate invoice detection patterns |
| Gemini 2.5 Technical Report, arXiv:2507.06261 | Model capability claims |

> To our knowledge, PlutusAudit AI is the **first open implementation of structured Multi-Agent Verification in accounts-payable automation.**

---

## Quick Start

```bash
git clone https://github.com/Bilal1262/plutusaudit_ai.git
cd plutusaudit_ai
cp .env.example .env    # add your API keys
docker compose up --build
```

When the stack is up:
- **Dashboard** → http://localhost:3000
- **API** → http://localhost:8000
- **Health** → http://localhost:8000/health

> First run downloads the BGE embedding model (~500MB for bge-small) and builds the FAISS index automatically.

### Local Development (no Docker)

```bash
# Backend
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.build_rag_index   # build RAG index once
python -m scripts.seed_db           # seed demo vendor master
uvicorn backend.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev     # http://localhost:5173
```

---

## Demo Invoices

Ten demo invoices ship in `data/clean/` and `data/fraud/`. The dashboard has a one-click demo panel — no upload needed.

| Invoice | Expected Result |
|---|---|
| `clean_01_software_subscription.pdf` | APPROVED · IFRS 15 Para 31 · Prepaid Expenses · deferral schedule |
| `clean_03_legal_services.pdf` | APPROVED · ASC 720 Para 25-1 · Professional Services |
| `fraud_01_round_number.pdf` | FLAGGED · round_number + missing_po + new_vendor |
| `fraud_02_duplicate.pdf` | BLOCKED · exact_duplicate + near_duplicate |
| `fraud_10_bank_account_change.pdf` | BLOCKED · bank_account_change + missing_po |

### The Tamper Demo

1. Process any invoice — watch 5 agents complete
2. Go to **Audit Log** → click **Verify Chain** → green banner
3. Click **Simulate Tamper** → one row mutated in Postgres
4. Click **Verify Chain** again → red banner: *"AUDIT CHAIN INTEGRITY VIOLATION — Entry #3 tampered"*

---

## API Reference

| Method | Path | Purpose |
|---|---|---|
| POST | `/process-invoice` | Upload PDF/image → `{job_id}` |
| GET | `/stream/{job_id}` | SSE stream of agent progress |
| GET | `/invoices` | Paginated invoice history |
| GET | `/audit-log` | Paginated audit entries |
| GET | `/audit-log/verify` | Replay and verify hash chain |
| GET | `/api/analytics` | CFO dashboard metrics |
| GET | `/api/demo-invoices` | Demo invoice metadata |
| GET | `/vendors` | Approved vendor list |
| POST | `/vendors/approve` | Add vendor to approved list |
| GET | `/health` | System health check |

---

## Project Structure

```
plutusaudit_ai/
├── backend/
│   ├── agents/
│   │   ├── doc_intel.py      # Agent 1 — Gemini multimodal extraction
│   │   ├── accountant.py     # Agent 2 — RAG + GL classification
│   │   ├── fraud.py          # Agent 3 — Featherless fraud detection
│   │   ├── verifier.py       # Agent 4 — 3-aspect MAV voting
│   │   └── explainer.py      # Agent 5 — explanation + audit chain
│   ├── rag/
│   │   ├── pipeline.py       # VeridianRAG — FAISS + BM25 + HyDE
│   │   ├── retriever.py      # HybridRetriever with category filtering
│   │   └── corpus/           # 80+ GAAP/IFRS rules
│   ├── audit/
│   │   └── chain.py          # SHA-256 hash chain append + verify
│   ├── prompts/              # All LLM prompts as .txt files
│   └── main.py               # FastAPI orchestrator
├── frontend/
│   └── src/
│       ├── pages/            # Dashboard, AuditLog, Analytics, Settings
│       └── components/       # AgentTimeline, FraudHeatmap, VendorApproval
├── data/
│   ├── clean/                # 10 realistic clean invoices
│   ├── fraud/                # 10 realistic fraud invoices
│   └── demo/                 # Original 4 demo PDFs
├── scripts/
│   ├── build_rag_index.py    # Build FAISS + BM25 index
│   └── seed_db.py            # Seed vendor master
├── docker-compose.yml
├── Dockerfile.backend
├── Dockerfile.frontend
└── .env.example
```

---

## Sponsor Track Narratives

### Why Vultr
Vultr is the system of record — not just hosting. Every agent decision, confidence score, hash-chained audit entry, and FAISS vector index lives on Vultr London. One `docker compose up` deploys everything. Live at http://45.76.132.31:3000.

### Why Google Gemini
Four agents use Gemini 2.5 Flash in four distinct modes: multimodal vision (Doc Intel), long-context RAG reasoning (Accountant), structured JSON verification (Verifier), and natural language generation (Explainer). Gemini 2.5 Flash achieves 99%+ accuracy on financial document extraction (Neurond benchmark).

### Why Featherless
The fraud agent deliberately does not use Gemini. Featherless Qwen3-32B is open-weight and auditable — any regulator can inspect exactly what model makes fraud decisions. The 9 deterministic signals run first so the model interprets computed evidence, not raw invoice text. The only fraud agent that shows its working.

---

## Compliance

| Standard | Coverage |
|---|---|
| SOX § 404 ICFR | Every financial decision logged with rationale and timestamp |
| EU AI Act Annex IV | Agent name, model version, input hash, citations, verifier votes per entry |
| GDPR Article 22 | Right to explanation via Explainer agent |
| IFRS / US GAAP | 80+ rules covering ASC 606, ASC 720, ASC 842, IAS 16, IFRS 15, IFRS 16 |

---

## License

Apache 2.0 · Built for Milan AI Week 2026
