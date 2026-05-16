# VeridianAI

**Self-auditing multi-agent enterprise finance.**
Five specialised AI agents extract, classify, fraud-check, verify and explain every invoice — and every decision they make is written to a SHA-256 hash-chained audit log that can detect a single byte of tampering.

> Built for the **AI Agent Olympics Hackathon — Milan AI Week 2026 (lablab.ai)**.
> Targeting the **Vultr ($10K)**, **Google Gemini ($10K)** and **Featherless (Pro plan)** prize tracks.

---

## The problem

> Companies process ~3 billion invoices per year. Manual AP coding, fraud
> review and audit-trail maintenance costs the global economy an estimated
> **$67.4 billion** annually, and post-AI hallucination scandals have made
> "the model said so" insufficient for finance.

VeridianAI is the first finance-grade agent stack that is **provably correct, demonstrably honest, and forensically auditable** end-to-end.

---

## Architecture

```
                        ┌──────────────┐
   PDF / image  ───►    │  Doc Intel   │  ◄── Gemini 2.5 Flash (multimodal)
                        └──────┬───────┘
                               ▼
                        ┌──────────────┐
                        │  Accountant  │  ◄── Gemini 2.5 Flash + HyDE-expanded
                        └──────┬───────┘      FAISS+BM25 hybrid RAG
                               ▼
                        ┌──────────────┐
                        │    Fraud     │  ◄── Featherless Qwen3-32B reasoning
                        └──────┬───────┘      over 9 deterministic signals
                               ▼
                ┌──────────────────────────────┐
                │   Verifier  ×3 aspect votes  │  ◄── Gemini 2.5 Flash
                │   numerical · citation · schema│      with retry loop
                └────────────────┬─────────────┘
                                 ▼
                        ┌──────────────┐
                        │  Explainer   │  ◄── Gemini 2.5 Flash
                        └──────┬───────┘
                               ▼
                ┌────────────────────────────┐
                │  Hash-chained audit log    │  ◄── SHA-256 append-only
                └────────────────────────────┘
```

Every agent emits an SSE event the frontend animates live. Every agent's decision is hashed into a chain you can replay to detect tampering.

---

## Track coverage

| Track            | What VeridianAI does                                                                                              |
| ---------------- | ----------------------------------------------------------------------------------------------------------------- |
| **Vultr**        | One-command `docker compose up` stack: FastAPI api + Postgres 16 db + Nginx-served React web. Production-ready.   |
| **Google Gemini**| Gemini 2.5 Flash powers 4 of the 5 agents — multimodal OCR, RAG-grounded GL classification, 2 of 3 verifiers, explainer. Native JSON mode end-to-end. |
| **Featherless** | Qwen3-32B drives the fraud reasoning stage, called via the OpenAI-compatible Featherless endpoint with rubric-anchored prompting. |

---

## Research basis

| Paper / Patent                                       | Where we use it                                            |
| ---------------------------------------------------- | ---------------------------------------------------------- |
| arXiv:2509.04469 (Berghaus et al., 2025)             | Native multimodal beats OCR pipeline in `doc_intel.py`     |
| arXiv:2504.14493 — **FinSage**                       | HyDE + hybrid FAISS+BM25 retrieval in `rag/`               |
| arXiv:2502.20379 — **Multi-Agent Verification (MAV)**| 3-aspect voting + retry in `verifier.py`                   |
| arXiv:2303.08896 — **SelfCheckGPT**                  | Faithfulness guard on RAG citations                        |
| Nigrini (1999) — Benford's Law                       | Vendor MAD signal in `fraud.py`                            |
| USPTO 12,045,215 & 12,106,384                        | Exact + near-duplicate invoice detection patterns          |
| RFC 6962 — Certificate Transparency                  | Hash-chained tamper-evident audit log design               |
| W3C SSE                                              | Live agent stream `/stream/{job_id}`                        |
| ISO 20022 / IFRS / US-GAAP                           | The chart of accounts + 20 rules in `gaap_ifrs_rules.txt`  |

---

## One-command setup

```bash
git clone <this-repo> veridianai && cd veridianai
cp .env.example .env             # then add your API keys
docker compose up --build
```

When the stack is up:
- **Frontend** → http://localhost:3000
- **Backend API** → http://localhost:8000
- **Health** → http://localhost:8000/health

> The first run downloads the BGE embedding model (~1.3 GB) and builds the FAISS index automatically the first time the RAG retriever loads.

### Local dev (no Docker)

```bash
# Backend
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# build the RAG index once
python -m scripts.build_rag_index
# seed the demo vendor master
python -m scripts.seed_db
# run the API
uvicorn backend.main:app --reload --port 8000

# Frontend (in another shell)
cd frontend
npm install
npm run dev          # http://localhost:5173, proxies /api -> :8000
```

---

## Demo script

Three demo PDFs ship in `data/demo/`:

| File                              | Expected behaviour                                                                                              |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `A_clean_software.pdf`            | $2,400 Acme Software annual subscription → DR Prepaid Expenses / CR Accounts Payable, IFRS 15 Para 31, confidence ≥ 0.95, **APPROVED**. |
| `B_fraud_duplicate.pdf`           | $4,950 below-threshold, vague description, no PO, near-duplicate of A → fraud score ≥ 65, tier **block**, **BLOCKED**. |
| `C_ambiguous_capex.pdf`           | Dell laptops + peripherals → split CAPEX vs expense under IAS 16 Para 7/10, verifier flags for human review.    |

### The tamper demo (the moment that wins the room)

1. Process invoice A. Watch all 5 circles turn green.
2. Open the **Audit Log** tab — 5 hash-chained entries appear.
3. Click **Verify Chain Integrity** → green banner: *"Audit chain verified — 5 entries intact."*
4. Click **Simulate tamper** → backend writes `_tampered: true` straight into the middle row's `output` JSON in Postgres.
5. Click **Verify Chain Integrity** again → red alarm banner: *"AUDIT CHAIN INTEGRITY VIOLATION — Entry #3 has been tampered with."*

The endpoint `/_demo/tamper/{entry_id}` is intentionally disabled when `ENVIRONMENT=production`.

---

## API surface

| Method | Path                                | Purpose                                          |
| ------ | ----------------------------------- | ------------------------------------------------ |
| POST   | `/process-invoice`                  | Upload PDF/image, returns `{job_id}`             |
| GET    | `/stream/{job_id}`                  | SSE stream of agent progress events              |
| GET    | `/invoices`                         | Paginated invoice history                        |
| GET    | `/invoices/{invoice_id}`            | Full pipeline result for one invoice             |
| GET    | `/audit-log`                        | Paginated audit entries (newest first)           |
| GET    | `/audit-log/verify`                 | Replay & verify the hash chain                   |
| POST   | `/audit-log/{entry_id}/override`    | Record a human override (append-only)            |
| GET    | `/vendors`                          | Vendor master list                               |
| GET    | `/health`                           | `{status, rag_loaded, db_connected, env}`        |
| POST   | `/_demo/tamper/{entry_id}`          | **Dev only.** Mutate a row to demo tamper alarm. |

### SSE event shape

```json
{
  "agent": "doc_intel|accountant|fraud|verifier|explainer|complete|error",
  "status": "running|complete|failed|retrying",
  "confidence": 0.94,
  "attempt": 1,
  "data": { /* agent-specific output */ },
  "timestamp": "2026-05-14T10:23:45Z"
}
```

---

## Project layout

```
veridianai/
├── backend/        FastAPI app + 5 agents + RAG + audit chain + DB
├── frontend/       React + Vite + Tailwind dashboard
├── data/           Demo PDFs, vendor history, ground-truth answers
├── scripts/        build_rag_index.py · seed_db.py · invoice/history generators
├── docker-compose.yml · Dockerfile.backend · Dockerfile.frontend
└── README.md
```

See the comments in each file for the per-component design rationale.

---

## Sponsor track narratives

### Why this is a Vultr-native build
The entire stack is `docker compose up`. We package three services (api, web, db) with healthchecks, named volumes for Postgres data and the FAISS index, and an Nginx layer that proxies `/api/` to FastAPI with SSE keep-alive enabled. Postgres 16 on a Vultr Cloud Compute instance is the production target. No managed services, no cloud-vendor lock-in — bring your own GPU instance for the embedding model.

### Why this is a Google Gemini showcase
Four of the five agents use Gemini 2.5 Flash. **Doc Intel** uses native multimodal — we send raw PNG bytes alongside the prompt and get back structured JSON in a single round-trip. **Accountant** uses Gemini's `response_mime_type="application/json"` mode for schema-locked GL classification grounded in retrieved IFRS / GAAP context. **Verifier** uses two Gemini-driven aspect checks (citation grounding + schema conformance) with a retry loop that demonstrates Gemini's strong instruction-following under critique. **Explainer** uses Gemini one last time to translate machine output into the AP manager's language. Every prompt lives in `backend/prompts/*.txt` so every Gemini call is auditable in Git.

### Why this is a Featherless build
The fraud agent is intentionally not Gemini. We use **Featherless Qwen3-32B** because (a) it lets us demonstrate the OpenAI-compatible inference API surface, (b) Qwen3-32B's stronger reasoning over tabular signals matches the fraud task better than smaller fast-turn models, and (c) running the fraud reasoning on a different provider proves the multi-vendor orchestration story that enterprise buyers ask about. The 9 deterministic signals run first (Benford MAD, near-duplicate Levenshtein, below-threshold heuristics) so the model receives a structured signal table, and Featherless reasons over signal interactions — the LLM cannot fabricate fraud, only interpret it.

---

## Tests

```bash
cd backend
pytest tests -q
```

Unit tests cover: arithmetic guard, Benford MAD, Levenshtein, vague-description heuristic, threshold detection, verifier numerical + schema checks, critique builder, **and an end-to-end hash-chain tamper test using an in-memory SQLite engine**.

---

## License

Apache 2.0. Built with love for Milan AI Week 2026.
