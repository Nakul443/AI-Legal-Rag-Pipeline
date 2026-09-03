# 📜 Legal + General RAG Pipeline

A production-grade pipeline that scrapes, parses, and classifies Indian regulatory PDFs into a queryable legal knowledge base — **and** now supports a second, domain-agnostic path for arbitrary user-uploaded PDFs (personal notes, general documents). Both are served through a single native MCP server, kept in separate vector tables, and never mixed with each other.

---

## 📑 Table of Contents

1. [What This System Does](#-what-this-system-does)
2. [Tech Stack](#-tech-stack)
3. [Architecture Overview](#-architecture-overview)
4. [Folder Structure](#-folder-structure)
5. [Data & Classification Models](#-data--classification-models)
6. [Service Deep-Dives](#-service-deep-dives)
   - [Scraper Service](#1-scraper-service)
   - [Processor Service — Legal Path](#2-processor-service--legal-path)
   - [Processor Service — General Path](#3-processor-service--general-path)
   - [API-RAG Service](#4-api-rag-service)
   - [MCP Tool Server](#5-mcp-tool-server)
7. [End-to-End Data Flow](#-end-to-end-data-flow)
8. [Environment Variables](#-environment-variables)
9. [Docker Setup](#-docker-setup)
10. [How to Run](#-how-to-run)
11. [AWS Deployment](#-aws-deployment)
12. [Built-In Safeguards](#-built-in-safeguards)

---

## 🛠 What This System Does

The pipeline now serves **two independent domains from one codebase**, sharing everything that's genuinely domain-agnostic (extraction, chunking, embedding, re-ranking) while keeping everything domain-specific (classification, prompts, storage tables) fully separate:

### Legal path (unchanged)
1. **Scrapes** government portals (CERC, APTEL, MNRE, MERC, and 10+ others), discovers PDF links, downloads them with structured JSON metadata.
2. **Guards** — SHA-256 hash every PDF; skip if already indexed.
3. **Classifies** — `DataOrchestrator` tags each document across four legal dimensions (Industry → Forum → Object Type → Legal Issue) and builds a deterministic storage path.
4. **Chunks & Embeds** — splits by legal section headers, embeds via OpenAI, stores in the `law_chunks` LanceDB table.
5. **Serves** — `search_legal_rag` MCP tool retrieves + re-ranks + answers via Gemini, with source citations.

### General path (new)
1. **Ingests** — a user uploads a PDF (typically via the chatbot's `/chat/upload` endpoint); the `ingest_pdf` MCP tool receives it as base64, decodes it, and runs it through the same extraction/chunking/embedding pipeline — no scraping, no legal classification.
2. **Stores** — chunks land in a separate `general_chunks` LanceDB table, each stamped with the uploading user's `user_id`.
3. **Serves** — `search_general` MCP tool retrieves only chunks belonging to the calling `user_id`, answers via a generic (non-legal) prompt.

Both paths share `PDFProcessor` (LlamaParse extraction), the chunker, and `Embedder` unchanged — only the classification/storage/prompt layers differ.

---

## 🧰 Tech Stack

| Layer | Technology |
|---|---|
| **Scraping** (legal only) | `crawl4ai`, `httpx`, `BeautifulSoup` |
| **PDF Parsing** (both paths) | `LlamaParse` (cloud OCR + table extraction → Markdown) |
| **Data Validation** | `Pydantic v2` — strict typed models for legal documents; plain dicts for general chunks |
| **Orchestration** | Pure Python + `asyncio` |
| **Embeddings** (both paths) | OpenAI (`text-embedding-3-small`) |
| **Re-Ranking** (both paths) | `cross-encoder/ms-marco-MiniLM-L-6-v2` via `sentence-transformers` |
| **Vector Database** | `LanceDB` — two tables, `law_chunks` and `general_chunks`, same file-based instance |
| **LLM Generation** | Google Gemini (`gemini-2.5-flash-lite`) — one prompt for `LegalAssistant`, a separate generic prompt for `GeneralAssistant` |
| **API Layer** | `FastAPI` + `uvicorn` (REST) and `FastMCP` (MCP over streamable HTTP) |
| **Cloud Storage** | AWS S3 via `boto3` (optional; mocked when keys are absent) |
| **Containerisation** | Docker + Docker Compose (four services: scraper + worker + REST API + MCP server) |
| **Config Format** | YAML (one file per scraping portal — legal path only) |
| **Runtime** | Python 3.11 |

---

## 🏗 Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        SCRAPER SERVICE (legal only)              │
│  configs/*.yaml ──► GenericCollector ──► data/raw/ (PDF + JSON)  │
└─────────────────────────────┬────────────────────────────────────┘
                              │  staging area (shared volume)
┌─────────────────────────────▼────────────────────────────────────┐
│                  PROCESSOR SERVICE — legal path                  │
│  worker.py ──► DataOrchestrator ──► Chunker ──► Embedder         │
│            └──► VectorStore(table="law_chunks")                  │
└─────────────────────────────┬────────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────────┐
│              PROCESSOR SERVICE — general path (new)              │
│  general_ingestor.py ──► PDFProcessor ──► Chunker ──► Embedder   │
│                       └──► VectorStore(table="general_chunks")   │
│  (no scraper, no DataOrchestrator — triggered on-demand           │
│   by the ingest_pdf MCP tool, not a background loop)              │
└─────────────────────────────┬────────────────────────────────────┘
                              │  shared LanceDB volume, two tables
┌─────────────────────────────▼────────────────────────────────────┐
│                        API-RAG SERVICE                           │
│  FastAPI /ask ──► RetrievalEngine(law_chunks) ──► Gemini         │
│                                                                    │
│  MCP SERVER (:8003) ──► search_legal_rag  (law_chunks)           │
│                     ──► search_general    (general_chunks,        │
│                                             filtered by user_id)   │
│                     ──► ingest_pdf        (writes general_chunks) │
└─────────────────────────────────────────────────────────────────┘
```

The four Docker containers (`legal_scraper`, `legal_processor_worker`, `legal_api_server`, `legal_mcp_server`) share the `data/` and `fml-raw-legal-store/` directories via bind mounts. `general_chunks` lives in the same LanceDB directory as `law_chunks` — no separate volume needed.

---

## 📂 Folder Structure

```text
LAWYER-RAG-PIPELINE/
│
├── data/                              # Staging area + LanceDB index (both tables live here)
│   └── raw/                           # Scraper staging: {uid}.pdf + {uid}.json pairs (legal only)
│
├── fml-raw-legal-store/               # Permanent organised legal file library (legal only)
│   └── POWER/ ...
│
├── models/
│   └── schema.py                      # Legal Pydantic models + Enums (general path doesn't use this)
│
├── services/
│   ├── api-rag/
│   │   └── src/
│   │       ├── main.py                # FastAPI app — POST /ask (legal REST endpoint)
│   │       ├── engine.py              # RetrievalEngine — table_name param, optional user_id filter
│   │       ├── assistant.py           # LegalAssistant (legal prompt) + GeneralAssistant (generic prompt)
│   │       └── mcp_server.py          # FastMCP server: search_legal_rag, search_general, ingest_pdf
│   │
│   ├── processor/
│   │   └── src/
│   │       ├── worker.py              # Legal ingestion loop — discovery, hash check, classify, embed, index
│   │       ├── general_ingestor.py    # General ingestion — one file at a time, no classification (new)
│   │       ├── data_orchestrator.py   # 4D legal classifier (legal path only)
│   │       ├── chunker.py             # Section-aware text splitter (shared by both paths)
│   │       ├── embedder.py            # OpenAI embedding wrapper (shared by both paths)
│   │       ├── vector_store.py        # LanceDB connection; table_name param (shared, parametrised)
│   │       ├── pdf_processor.py       # LlamaParse PDF → Markdown extractor (shared by both paths)
│   │       ├── s3_manager.py          # AWS S3 upload wrapper (legal path)
│   │       └── test_search.py         # CLI RAG test (legal path)
│   │
│   └── scraper/                       # Legal path only — unchanged
│       ├── configs/*.yaml
│       └── src/main.py, collectors/, utils/
│
├── Dockerfile
├── docker-compose.yml                 # legal_scraper + legal_processor_worker + legal_api_server + legal_mcp_server
├── .env.example
├── .gitignore
├── .dockerignore
└── requirements.txt
```

---

## 🧩 Data & Classification Models

> **File:** `models/schema.py` — used by the **legal path only**. The general path deliberately avoids this schema; a general chunk is a plain dict (`text`, `vector`, `title`, `source`, `page`, `user_id`, `upload_date`, `duplicate_hash`), not a `LegalDocument`.

### Enums (legal path vocabulary)

| Enum | Values | Purpose |
|---|---|---|
| `Industry` | `POWER`, `TELECOM` | D1 — top-level industry domain |
| `Forum` | `CERC`, `APTEL`, `SC`, `HC_DELHI`, `HC_BOMBAY`, `SERC_MH`, and more | D2 — regulatory body or court |
| `LegalObjectType` | `JUDGMENT`, `INTERIM_ORDER`, `REGULATION`, `AMENDMENT`, `TARIFF_ORDER`, `NOTIFICATION`, `POLICY` | D3 — document type |
| `LegalIssue` | `OPEN_ACCESS`, `CHANGE_IN_LAW`, `TARIFF`, `GNA_CONNECTIVITY`, `DSM`, `CAPTIVE`, `RPO`, `SCHEDULING_FORECASTING`, `BANK_GUARANTEE`, `WRIT`, `OTHER` | D4 — legal subject matter |
| `ChallengeStatus` | `FINAL`, `UNDER_APPEAL`, `STAYED`, `REMANDED` | Legal finality |

### Pydantic Models (legal path)

**`LegalDocument`** — core, classification, and provenance fields, plus `pending_*` boolean flags that track any unpopulated value.

**`LegalChunk`** — vector-ready slice: `chunk_id`, `parent_id`, `text`, `vector`, `duplicate_hash`, `authority`, `issue_tag_primary`, `section_header`, `category`.

### General chunk shape (general path — no Pydantic model, plain dict)

| Field | Purpose |
|---|---|
| `text` | Context-injected chunk text (same injection pattern as legal chunks) |
| `vector` | Embedding, `text-embedding-3-small` |
| `title` / `source` | Original filename |
| `page` | Page number, if available |
| `user_id` | Owner — every `search_general` call filters on this |
| `upload_date` | When the chunk was ingested |
| `duplicate_hash` | SHA-256, scoped **per user** — two different users uploading the same PDF are not treated as duplicates of each other |

---

## 🔍 Service Deep-Dives

### 1. Scraper Service

Unchanged from the legal-only version. **Entry point:** `services/scraper/src/main.py`. Scans `services/scraper/configs/` for `.yaml` files, runs a `GenericCollector` per portal, writes PDF+JSON pairs to `data/raw/`.

**Configured portals:** CERC, APTEL, MNRE, MERC, CEA, DERC, GERC, KERC, SECI, TNERC, UPERC, WBERC, BEE, Ministry of Power.

---

### 2. Processor Service — Legal Path

**Entry point:** `services/processor/src/worker.py` — background loop, picks up everything in `data/raw/`.

```
for each {uid}.json + {uid}.pdf pair in data/raw/:
  1. file_size_bytes == 0? → skip (download failed)
  2. SHA-256 hash → SQLite StateManager already 'indexed'? → skip
  3. LanceDB has_document_hash(hash)? → skip (WORM dedup)
  4. LlamaParse → clean Markdown
  5. enrich_metadata() → act name, year, category
  6. Validate authority/challenge_status against enums
  7. Build LegalDocument (Pydantic) with pending flags
  8. DataOrchestrator.route_document() → D3/D4 classification + deterministic path
  9. Copy PDF to fml-raw-legal-store/{path}/{filename}
 10. Chunker.prepare_for_lancedb() → LegalChunk objects
 11. Embedder.get_embeddings() → OpenAI, batched, retried on 429
 12. VectorStore(table="law_chunks").upsert_chunks()
 13. StateManager.update_status('indexed')
 14. Delete data/raw/{uid}.json + .pdf only after confirmed write
```

`data_orchestrator.py` classifies D3 (object type) and D4 (legal issue) via keyword matching, and builds the deterministic `fml-raw-legal-store/` path (e.g. `POWER/CERC/JUDGMENTS/OPEN_ACCESS/`).

---

### 3. Processor Service — General Path

**Entry point:** `services/processor/src/general_ingestor.py` — **not** a background loop. It's a single-file, on-demand entry point called synchronously by the `ingest_pdf` MCP tool, once per upload:

```
general_ingestor.ingest(file_path, user_id, source_name):
  1. SHA-256 hash the file, scoped to user_id (same user re-uploading
     the same PDF is deduped; two different users are not)
  2. PDFProcessor (LlamaParse) → clean Markdown        [same class as legal path]
  3. Chunker.chunk_text() → section/paragraph chunks    [same class as legal path]
  4. Embedder.get_embeddings()                           [same class as legal path]
  5. VectorStore(table="general_chunks").upsert_chunks()
     — each record stamped with user_id, source_name, upload_date
  6. Returns a short confirmation (chunk count indexed) or an error string
```

No `DataOrchestrator` call, no legal enums, no deterministic filing path — this path exists purely to get an arbitrary user's PDF searchable under their own `user_id`, as fast as possible.

---

### 4. API-RAG Service

**Entry point:** `services/api-rag/src/main.py` — `POST /ask`, legal path only (unchanged REST contract).

#### `engine.py` — RetrievalEngine
Now parametrised by `table_name`, so two instances are created in `mcp_server.py` — one bound to `law_chunks`, one to `general_chunks`. `search()` takes an optional `user_id` filter (used only by the general-table instance) alongside the existing `jurisdiction` filter (legal-table only). Retrieval is still two-stage: top-50 vector search candidates, re-ranked down to the top 5 with a local `CrossEncoder`.

#### `assistant.py` — two assistants
- **`LegalAssistant`** — unchanged: "Indian Regulatory & Legal Expert" system prompt, citation rules, `gemini-2.5-flash-lite`.
- **`GeneralAssistant`** (new) — generic prompt: "answer using only the provided context, say so if the answer isn't in the context." No legal framing, no citation-of-authority instructions.

---

### 5. MCP Tool Server

**Entry point:** `services/api-rag/src/mcp_server.py` — native MCP server over streamable HTTP, port `8003`, same `BearerAuthMiddleware` (`MCP_AUTH_TOKEN`) protecting every path under `/mcp`.

| Tool | Table | Scoped by | Purpose |
|---|---|---|---|
| `search_legal_rag(query, jurisdiction?)` | `law_chunks` | — (shared knowledge base) | Search + answer over regulatory/legal documents |
| `search_general(query, user_id)` | `general_chunks` | `user_id` | Search + answer over one user's own uploaded PDFs only |
| `ingest_pdf(file_base64, filename, user_id)` | writes to `general_chunks` | `user_id` | Index a newly uploaded PDF for that user, on demand |

All three run in the same FastMCP process — one port, one auth token, no separate deployment needed for the general path.

---

## 🔄 End-to-End Data Flow

### Legal path (unchanged)
```
scraper configs → GenericCollector → data/raw/{uid}.pdf+.json
   → worker.py → hash/dedup check → LlamaParse → DataOrchestrator (D3/D4)
   → chunker (context-injected) → Embedder → VectorStore(law_chunks)
   → cleanup data/raw/
   → search_legal_rag: embed query → vector search top 50 → re-rank top 5
     → LegalAssistant (Gemini) → { answer, sources }
```

### General path (new)
```
user uploads PDF via chatbot → ingest_pdf(file_base64, filename, user_id)
   → decode → PDFProcessor (LlamaParse) → chunker → Embedder
   → VectorStore(general_chunks), stamped with user_id → confirmation string
                                    │
   later: search_general(query, user_id)
     → embed query → vector search top 50, filtered to user_id → re-rank top 5
     → GeneralAssistant (Gemini) → answer string
```

---

## 🔑 Environment Variables

```env
# LLM & Parsing APIs
OPENAI_API_KEY=your_openai_api_key_here
GEMINI_API_KEY=your_gemini_api_key_here
LLAMAPARSE_API_KEY=your_llamaparse_api_key_here

# AWS S3 (optional — mocked if absent; legal path only)
AWS_ACCESS_KEY_ID=your_aws_access_key_here
AWS_SECRET_ACCESS_KEY=your_aws_secret_key_here
AWS_DEFAULT_REGION=us-east-1
AWS_S3_BUCKET_NAME=your_legal_raw_pdfs_bucket

# Vector DB — both law_chunks and general_chunks live under this path
LANCE_DB_PATH=/app/data/index/legal_vdb

# MCP server auth — must match LEGAL_RAG_AUTH_TOKEN in the chatbot repo's .env
MCP_AUTH_TOKEN=your-secure-mcp-auth-token

ENVIRONMENT=development
```

---

## 🐋 Docker Setup

Single `Dockerfile` (Python 3.11-slim), `docker-compose.yml` runs four services from it:

| Service | Command | Port | Volumes |
|---|---|---|---|
| `legal_scraper` | `python3 services/scraper/src/main.py` | — | `./data` |
| `legal_processor_worker` | `python3 services/processor/src/worker.py` | — | `./data`, `./fml-raw-legal-store` |
| `legal_api_server` | `python3 services/api-rag/src/main.py` | `8000` | `./data`, `./fml-raw-legal-store` |
| `legal_mcp_server` | `python3 services/api-rag/src/mcp_server.py` | `8003` | `./data`, `./fml-raw-legal-store` |

`general_ingestor.py` isn't its own service — it's invoked in-process by `legal_mcp_server` whenever `ingest_pdf` is called, so it needs no separate container.

```bash
docker-compose up --build              # everything
docker-compose up legal_mcp_server     # just the MCP server (both search_legal_rag and search_general/ingest_pdf)
```

---

## 🚀 How to Run

### Prerequisites
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Legal path
```bash
python services/scraper/src/main.py      # scrape
python services/processor/src/worker.py  # classify, chunk, embed, index
python services/api-rag/src/main.py      # REST API at :8000, docs at /docs
```

### General path — no separate script to run
General ingestion only happens through the MCP server's `ingest_pdf` tool — there's no standalone CLI equivalent to `worker.py` for this path, since it's designed to be triggered on-demand per upload, not run as a batch job.

### Start the MCP Server (serves both paths)
```bash
python services/api-rag/src/mcp_server.py
```
Live at `http://localhost:8003`. If `MCP_AUTH_TOKEN` is set, every `/mcp` request needs `Authorization: Bearer <token>`; unset for unauthenticated local dev.

**Exposed tools:** `search_legal_rag(query, jurisdiction?)`, `search_general(query, user_id)`, `ingest_pdf(file_base64, filename, user_id)` — see [MCP Tool Server](#5-mcp-tool-server) above.

---

## ☁️ AWS Deployment

Unchanged from the legal-only version — Docker directly on EC2, no ECS/Kubernetes needed.

**Recommended instance:** `t3.large`/`t3.xlarge`. **Storage:** EBS `gp3` (200GB+) mounted at `/app/data/` and `/app/fml-raw-legal-store/` — `general_chunks` lives in the same `data/` mount, no extra volume required.

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose
git clone https://github.com/your-username/findmylawyer.git && cd findmylawyer
ln -s /mnt/legal-data/data ./data
ln -s /mnt/legal-data/fml-raw-legal-store ./fml-raw-legal-store
cp .env.example .env   # fill in keys
docker-compose up --build -d legal_processor_worker legal_api_server legal_mcp_server
docker-compose run --rm legal_scraper   # one-shot, or via cron
```

**Security group:** open `8000` (REST) and `8003` (MCP) — or front both with a reverse proxy.

**Cross-repo note:** if the chatbot repo runs as a separate Docker Compose project (possibly on a different host), point its `LEGAL_RAG_MCP_URL` at this instance's public/internal address on port `8003`, not `localhost`.

---

## 🛡 Built-In Safeguards

**Legal path (unchanged):** WORM deduplication (SHA-256, checked in `law_chunks`), SQLite state tracking, atomic cleanup (raw files deleted only after confirmed LanceDB write), failed-download guard, pending-flag tracking, exponential backoff on 429s, `asyncio.Semaphore(3)` concurrency limiting, schema-evolution handling in `VectorStore.upsert_chunks()`, YAML config validation at startup, two-stage retrieval (50 candidates → re-rank → top 5).

**General path (new):**
- **Per-user WORM dedup** — SHA-256 hash scoped to `user_id`, so re-uploading the same file wastes no embedding calls, while different users' identical files are correctly kept separate.
- **User isolation at query time** — `search_general` always filters on `user_id`; there is no code path where one user's uploaded chunks can surface in another user's results.
- **Schema evolution risk** — `VectorStore.upsert_chunks()`'s overwrite-on-mismatch fallback applies to `general_chunks` too. Once real user data is in that table, a careless schema change (e.g. adding a field without a migration path) could wipe it — same risk that already existed on the legal side, now also relevant here since general data isn't re-derivable from a re-scrape the way legal data is.