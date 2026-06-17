# 📜 FindMyLawyer — Legal RAG Ingestion Pipeline

A production-grade pipeline that automatically scrapes regulatory PDFs from Indian electricity regulatory bodies, parses and classifies them across four legal dimensions, chunks and embeds them into a semantic vector database, and exposes them via a RAG-powered API for AI-assisted legal research.

---

## 📑 Table of Contents

1. [What This System Does](#-what-this-system-does)
2. [Tech Stack](#-tech-stack)
3. [Architecture Overview](#-architecture-overview)
4. [Folder Structure](#-folder-structure)
5. [Data & Classification Models](#-data--classification-models)
6. [Service Deep-Dives](#-service-deep-dives)
   - [Scraper Service](#1-scraper-service)
   - [Processor Service](#2-processor-service)
   - [API-RAG Service](#3-api-rag-service)
7. [End-to-End Data Flow](#-end-to-end-data-flow)
8. [Environment Variables](#-environment-variables)
9. [Docker Setup](#-docker-setup)
10. [How to Run](#-how-to-run)
11. [Built-In Safeguards](#-built-in-safeguards)

---

## 🛠 What This System Does

The pipeline solves one hard problem: turning a flood of unstructured government legal PDFs into a queryable, AI-ready knowledge base — automatically, without duplicates, without data loss, and with rich structured metadata at every step.

At a high level it does five things in sequence:

1. **Scrapes** — visits government portals (CERC, APTEL, MNRE, MERC, and 10+ others), discovers PDF links via configurable CSS selectors, downloads the PDFs, and saves them alongside structured JSON metadata in a staging directory.
2. **Guards** — every PDF is SHA-256 hashed on arrival. Before any expensive work begins, the hash is checked against LanceDB. Duplicate documents are skipped entirely, protecting embedding API quota.
3. **Classifies & Routes** — the `DataOrchestrator` reads title and content to tag each document across four legal dimensions (Industry → Forum → Object Type → Legal Issue) and builds a deterministic storage path like `POWER/CERC/JUDGMENTS/OPEN_ACCESS/`.
4. **Chunks & Embeds** — the `DocumentProcessor` slices documents by legal section headers (Section, Article, Chapter, Clause) rather than arbitrary character counts, so clauses are never split mid-sentence. Each chunk is then embedded via the Gemini Embedding API into a 1536-dimensional vector.
5. **Indexes & Serves** — vectors and rich metadata are stored in a local LanceDB table (`law_chunks`). A FastAPI service wraps a `RetrievalEngine` that converts user questions into vectors, retrieves the top-K most relevant chunks, and feeds them to Gemini to generate legally grounded answers with source citations.

---

## 🧰 Tech Stack

| Layer | Technology |
|---|---|
| **Scraping** | `crawl4ai` (async headless browser), `httpx` (lightweight fetcher), `BeautifulSoup` |
| **PDF Parsing** | `LlamaParse` (cloud OCR + table extraction → Markdown) |
| **Data Validation** | `Pydantic v2` — strict typed models and enums for every document |
| **Orchestration** | Pure Python + `asyncio` — async pipeline from scrape to index |
| **Embeddings** | Google Gemini (`gemini-embedding-001`) via `google-genai` SDK |
| **Vector Database** | `LanceDB` (local file-based, queryable with SQL-like filters) |
| **LLM Generation** | Google Gemini (`gemini-2.5-flash` / `gemini-2.5-flash-lite`) |
| **API Layer** | `FastAPI` + `uvicorn` |
| **Cloud Storage** | AWS S3 via `boto3` (optional; mocked when keys are absent) |
| **Containerisation** | Docker + Docker Compose (two services: worker + API) |
| **Config Format** | YAML (one file per scraping portal) |
| **Runtime** | Python 3.11 |

---

## 🏗 Architecture Overview

The system is split into three independently runnable services that share a common schema and two shared volumes:

```
┌─────────────────────────────────────────────────────────────────┐
│                        SCRAPER SERVICE                          │
│  configs/*.yaml ──► GenericCollector ──► data/raw/ (PDF + JSON) │
└─────────────────────────────┬───────────────────────────────────┘
                              │  staging area
┌─────────────────────────────▼───────────────────────────────────┐
│                       PROCESSOR SERVICE                         │
│  worker.py ──► DataOrchestrator ──► Chunker ──► Embedder        │
│            └──► VectorStore (LanceDB) ──► fml-raw-legal-store/  │
└─────────────────────────────┬───────────────────────────────────┘
                              │  shared LanceDB volume
┌─────────────────────────────▼───────────────────────────────────┐
│                        API-RAG SERVICE                          │
│  FastAPI /ask ──► RetrievalEngine ──► LegalAssistant (Gemini)   │
└─────────────────────────────────────────────────────────────────┘
```

The two Docker containers (`legal_processor_worker` and `legal_api_server`) share the `data/` and `fml-raw-legal-store/` directories via bind mounts, so the API can read the same LanceDB the worker writes to.

---

## 📂 Folder Structure

```text
LAWYER-RAG-PIPELINE/
│
├── data/                              # LanceDB index lives here (data/index/legal_vdb/)
│
├── fml-raw-legal-store/               # Permanent organised legal file library
│   └── POWER/
│       ├── CERC/
│       │   ├── JUDGMENTS/OPEN_ACCESS/
│       │   ├── REGULATIONS/
│       │   └── TARIFF_ORDERS/
│       ├── APTEL/
│       │   ├── JUDGMENTS/
│       │   └── REVIEW_PETITIONS/
│       ├── SUPREME_COURT/
│       └── HIGH_COURTS/DELHI/JUDGMENTS/WRIT/
│
├── models/
│   └── schema.py                      # Single source of truth: Pydantic models + all Enums
│
├── services/
│   ├── api-rag/
│   │   └── src/
│   │       ├── main.py                # FastAPI app — POST /ask endpoint
│   │       ├── engine.py              # RetrievalEngine — vectorises query, searches LanceDB
│   │       └── assistant.py           # LegalAssistant — Gemini prompt builder & caller
│   │
│   ├── processor/
│   │   └── src/
│   │       ├── worker.py              # Main pipeline loop — discovery, hash check, orchestrate, embed, index
│   │       ├── data_orchestrator.py   # 4D classifier + deterministic path & filename generator
│   │       ├── chunker.py             # Section-aware text splitter + LanceDB record builder
│   │       ├── embedder.py            # Gemini embedding API wrapper with rate-limit handling
│   │       ├── vector_store.py        # LanceDB connection, upsert, hash-dedup query
│   │       ├── pdf_processor.py       # LlamaParse async PDF → Markdown extractor
│   │       ├── s3_manager.py          # AWS S3 upload wrapper (gracefully mocked if no keys)
│   │       └── test_search.py         # CLI RAG test — embed a query, retrieve chunks, generate answer
│   │
│   └── scraper/
│       ├── configs/                   # One YAML per portal (cerc, aptel, mnre, merc, etc.)
│       │   ├── cerc.yaml
│       │   ├── aptel.yaml
│       │   ├── mnre.yaml
│       │   └── ...
│       └── src/
│           ├── main.py                # Scraper entry point — loops over all configs, runs collectors
│           ├── collectors/
│           │   └── generic_collector.py   # Core crawler: CSS selector extraction + PDF download
│           └── utils/
│               └── config_loader.py       # YAML loader + strict forum/state enum validation
│
├── Dockerfile                         # Single image for both worker and API (CMD overridden in compose)
├── docker-compose.yml                 # Two services: legal_processor_worker + legal_api_server
├── .env.example                       # All required environment variable keys
├── .gitignore                         # Excludes data/, PDFs, .env, venv
├── .dockerignore
└── requirements.txt                   # All Python dependencies
```

---

## 🧩 Data & Classification Models

> **File:** `models/schema.py` — imported by every service. Never duplicated.

### Enums (the classification vocabulary)

| Enum | Values | Purpose |
|---|---|---|
| `Industry` | `POWER`, `TELECOM` | D1 — top-level industry domain |
| `Forum` | `CERC`, `APTEL`, `SC`, `HC_DELHI`, `HC_BOMBAY`, `SERC_MH`, `SERC_GJ`, `SERC_KA`, `SERC_RJ`, `SERC_TN` | D2 — the regulatory body or court |
| `LegalObjectType` | `JUDGMENT`, `INTERIM_ORDER`, `REGULATION`, `AMENDMENT`, `TARIFF_ORDER`, `NOTIFICATION`, `POLICY` | D3 — what type of document it is |
| `LegalIssue` | `OPEN_ACCESS`, `CHANGE_IN_LAW`, `TARIFF`, `GNA_CONNECTIVITY`, `DSM`, `CAPTIVE`, `RPO`, `SCHEDULING_FORECASTING`, `BANK_GUARANTEE`, `WRIT`, `OTHER` | D4 — the core legal subject matter |
| `ChallengeStatus` | `FINAL`, `UNDER_APPEAL`, `STAYED`, `REMANDED` | Legal finality of the order |

### Pydantic Models

**`LegalDocument`** — the parent record, created at scrape time and enriched by the processor:
- Core fields: `uid`, `title`, `source_url`, `content_markdown`, `duplicate_hash`
- Classification fields: `authority` (Forum), `legal_object_type`, `issue_tag_primary`, `industry`
- Provenance fields (Section 4.1): `source_domain`, `scrape_date`, `pipeline_version`, `file_size_bytes`
- Pending flags (Section 4.2): `pending_date_of_order`, `pending_source_url`, `pending_state`, etc. — boolean fields that auto-track every unpopulated value so nothing silently falls through

**`LegalChunk`** — a vector-ready slice of a parent document, stored in LanceDB:
- `chunk_id`, `parent_id`, `text` (context-injected), `vector`
- Carries `duplicate_hash` (inherited from parent) so the WORM dedup query can run against the `law_chunks` table
- Carries `authority`, `issue_tag_primary`, `section_header`, `category` for filtered vector search

---

## 🔍 Service Deep-Dives

### 1. Scraper Service

**Entry point:** `services/scraper/src/main.py`

On startup it scans `services/scraper/configs/` for every `.yaml` file, instantiates a `GenericCollector` for each, and runs them sequentially.

#### `config_loader.py`
Loads a portal's YAML and runs strict validation before returning it:
- Checks all required keys are present: `site_name`, `forum`, `state`, `jurisdiction`, `base_url`, `start_url`
- Validates `forum` against the known `Forum` enum member names
- Validates `state` against known state codes (`CENTRAL`, `MH`, `GJ`, etc.)
- Fails loudly at startup so bad configs never reach the crawler

#### `generic_collector.py`
The actual crawler. For each portal it:
1. Detects direct PDF links (e.g. TNERC) and bypasses the browser entirely for them
2. Otherwise uses `crawl4ai`'s async headless browser with a configurable `wait_for` CSS selector and a 2-second JS settle delay
3. Parses the rendered HTML with `BeautifulSoup` using the `row`, `title`, `link`, and `date` selectors from the YAML
4. Downloads each discovered PDF via `httpx` with browser-spoofing `User-Agent` headers
5. Writes two files to `data/raw/`: `{uid}.pdf` and `{uid}.json`

The JSON carries all Section 4.1 provenance fields populated at scrape time: `authority`, `state`, `jurisdiction`, `source_domain`, `scrape_date`, `pipeline_version`, and `file_size_bytes`. If the PDF download fails, `file_size_bytes` is set to `0` — this is the signal `worker.py` uses to skip the pair without crashing.

#### YAML config structure
Each portal config declares:

```yaml
site_name: "CERC"
forum: "CERC"               # Must match a Forum enum member name
state: "CENTRAL"            # Must match a valid state code
jurisdiction: "Central"
base_url: "https://cercind.gov.in"
start_url: "https://cercind.gov.in/recent_orders.html"
wait_for: "table"           # CSS selector to wait for before parsing

selectors:
  row: "table.table tbody tr"
  title: "td:nth-child(3)"
  link: "td:nth-child(3) a, td:nth-child(4) a"
  date: "td:nth-child(2)"
```

**Configured portals:** CERC, APTEL, MNRE, MERC, CEA, DERC, GERC, KERC, SECI, TNERC, UPERC, WBERC, BEE, Ministry of Power

---

### 2. Processor Service

**Entry point:** `services/processor/src/worker.py`

The main async loop that picks up from where the scraper left off. It scans `data/raw/` for JSON+PDF pairs and processes each one through the full pipeline.

#### `worker.py` — step by step

```
for each {uid}.json + {uid}.pdf pair in data/raw/:

  1. Read JSON → check file_size_bytes == 0 → skip if PDF download failed
  2. SHA-256 hash the PDF
  3. Query LanceDB: has_document_hash(hash) → skip if already indexed (WORM check)
  4. LlamaParse: async extract PDF → clean Markdown
  5. enrich_metadata(): extract act name, year, category from title + content
  6. Validate authority string → Forum enum; validate challenge_status → ChallengeStatus enum
  7. Build LegalDocument (Pydantic) with all fields + pending flags
  8. DataOrchestrator.route_document() → classify D3/D4, generate path + filename
  9. shutil.copy2() → copy PDF to deterministic path in fml-raw-legal-store/
  10. DocumentProcessor.prepare_for_lancedb() → list of LegalChunk objects
  11. Embedder.get_embeddings() → vectors in batches of 30, with 2s cooldown between batches
      → On 429/RESOURCE_EXHAUSTED: sleep 60s and retry (per-minute limit)
      → On quota exhausted: abort this document, do not delete raw files
  12. VectorStore.upsert_chunks() → write to LanceDB
  13. Only on confirmed success: delete {uid}.json and {uid}.pdf from data/raw/
```

The cleanup-last design is critical: raw files are only deleted after a confirmed LanceDB write. A failed upsert or network drop leaves the raw files in place for the next run.

#### `data_orchestrator.py` — 4D classification

`classify_dimensions()` scans the first 4000 characters of title + content for keyword patterns:

- **D3 (Object Type):** Checks in priority order — AMENDMENT → REGULATION → TARIFF_ORDER → INTERIM_ORDER → NOTIFICATION → POLICY → JUDGMENT (fallback). Sets `pending_legal_object_type = True` if the fallback was used without finding "JUDGMENT" or "ORDER" in the text.
- **D4 (Legal Issue):** Matches against an `issue_map` of keyword lists. WRIT is specifically mapped to detect High Court writ petitions. Sets `pending_issue_tag_primary = True` if nothing matched.

`generate_deterministic_path()` builds the folder path:
- SERC forums expand to `SERC/{STATE_NAME}/`
- HC forums expand to `HIGH_COURTS/{COURT_NAME}/`
- SC becomes `SUPREME_COURT/`
- Object types are pluralised: `JUDGMENTS`, `REGULATIONS`, `TARIFF_ORDERS`, etc.
- Adjudicatory types (JUDGMENT, INTERIM_ORDER) get an issue sub-folder: `.../JUDGMENTS/OPEN_ACCESS/`
- Legislative types (REGULATION, AMENDMENT, POLICY) are flat: `.../REGULATIONS/`
- APTEL review petitions get their own `REVIEW_PETITIONS/` branch

`format_filename()` produces structured names like:
- Orders: `CERC_OPEN_ACCESS_TATA_V_PGCIL_2024_JUDGMENT.pdf`
- Regulations: `CERC_OPEN_ACCESS_REGULATION_2023_V1.pdf`

#### `chunker.py` — section-aware splitting

Splits text by a regex that matches `Section N`, `Sec. N`, `Article N`, `Chapter N`, `Clause N`. Each matched header and the content that follows it until the next header becomes one chunk. If a section exceeds 1500 characters it is sub-chunked with 200-character overlap.

Every chunk gets context injected at the top before embedding:
```
ACT: {act_name}
SECTION: {section_header}

{chunk_content}
```

This ensures that when a chunk is retrieved in isolation, the embedding model and the LLM both know which document and section it came from.

#### `embedder.py`

Wraps the `google-genai` SDK's `embed_content` method using `gemini-embedding-001` with task type `RETRIEVAL_DOCUMENT`. Accepts a list of strings and returns a list of float vectors. Rate-limit handling (429 / RESOURCE_EXHAUSTED) is managed in `worker.py`'s retry loop.

#### `vector_store.py`

Connects to LanceDB at `data/index/legal_vdb`. Key methods:
- `has_document_hash(hash)` — queries `law_chunks` by `duplicate_hash` column; returns `False` (not `True`) if the table doesn't exist yet, so the first run always proceeds
- `upsert_chunks(records)` — converts all Enum values to strings (LanceDB requires plain types), casts vectors to `float32`, creates or appends to the `law_chunks` table; handles schema evolution by recreating the table if a schema mismatch is detected
- `query(vector, limit, filter_str)` — vector search with optional SQL-like filter string (e.g. `"jurisdiction = 'CERC'"`)

#### `pdf_processor.py`

Sends the PDF to LlamaParse using 4 parallel workers for faster processing of large regulatory files. Returns clean Markdown including tables, which is critical for tariff orders and annexures that would be garbled by a standard PDF text extractor.

#### `s3_manager.py`

Uploads files to the configured S3 bucket. If `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, or `S3_BUCKET_NAME` are absent from the environment, it initialises in mock mode and prints the intended action instead of crashing — safe for local development.

#### `test_search.py`

A standalone CLI test script. Takes a query string, embeds it, searches LanceDB for 10 chunks, builds a prompt with source metadata (authority, issue tag, challenge status, section header), sends it to `gemini-2.5-flash`, and prints the answer with source citations. Includes a 3-attempt retry on 503 upstream errors.

---

### 3. API-RAG Service

**Entry point:** `services/api-rag/src/main.py`

A FastAPI application exposing a single endpoint:

```
POST /ask
{
  "question": "How is open access categorised based on duration?",
  "jurisdiction": "CERC",   // optional LanceDB filter
  "limit": 5                // number of chunks to retrieve
}
```

#### `engine.py` — RetrievalEngine

Reuses the same `Embedder` from the processor service (imported via `sys.path`). On a query:
1. Embeds the user question with `gemini-embedding-001`
2. Opens the `law_chunks` LanceDB table
3. Runs a vector search with an optional `jurisdiction` filter
4. Returns up to `limit` results as plain dicts

#### `assistant.py` — LegalAssistant

Builds a structured prompt from the retrieved chunks:
- System role: "highly skilled Indian Regulatory & Legal Expert"
- Rules injected: do not hallucinate, cite sources, stay precise
- Calls `gemini-2.5-flash-lite` for cost-efficient generation

The API auto-generates interactive docs at `http://localhost:8000/docs` via FastAPI's built-in Swagger UI — no frontend needed for testing.

---

## 🔄 End-to-End Data Flow

```
services/scraper/configs/*.yaml
         │
         ▼
main.py ──► GenericCollector.collect_links()
                │  crawl4ai browser / httpx
                │  BeautifulSoup CSS selector parsing
                ▼
         PDF + JSON ──► data/raw/{uid}.pdf + {uid}.json
                              │
                              ▼
                        worker.py picks up pair
                              │
                    ┌─────────┴──────────┐
                    │  file_size_bytes=0? │──► SKIP (PDF download failed)
                    └─────────┬──────────┘
                              │
                    ┌─────────┴──────────────────┐
                    │  duplicate_hash in LanceDB? │──► SKIP (WORM dedup)
                    └─────────┬──────────────────┘
                              │
                        LlamaParse → raw Markdown
                              │
                        enrich_metadata() → act_name, year, category
                              │
                        Pydantic LegalDocument (with pending flags)
                              │
                        DataOrchestrator.route_document()
                         ├── classify_dimensions() → D3 + D4
                         ├── generate_deterministic_path() → folder
                         └── format_filename() → filename
                              │
                        shutil.copy2() → fml-raw-legal-store/{path}/{filename}
                              │
                        DocumentProcessor.prepare_for_lancedb()
                         └── chunk_text() → section-aware chunks
                         └── context injection per chunk
                         └── LegalChunk objects (with duplicate_hash)
                              │
                        Embedder.get_embeddings() [batches of 30]
                         └── gemini-embedding-001 → float vectors
                              │
                        VectorStore.upsert_chunks() → LanceDB law_chunks table
                              │
                        Cleanup: delete data/raw/{uid}.json + {uid}.pdf
                              │
                              ▼
                     ┌─────────────────────┐
                     │  FastAPI POST /ask   │
                     └──────────┬──────────┘
                                │
                     RetrievalEngine.search()
                      ├── embed question → vector
                      └── LanceDB vector search (+ optional filter)
                                │
                     LegalAssistant.ask_legal_question()
                      └── Gemini prompt with citations
                                │
                                ▼
                     JSON response: { answer, sources }
```

---

## 🔑 Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```env
# LLM & Parsing APIs
GEMINI_API_KEY=your_gemini_api_key_here
LLAMAPARSE_API_KEY=your_llamaparse_api_key_here

# AWS S3 (optional — pipeline mocks S3 if these are absent)
AWS_ACCESS_KEY_ID=your_aws_access_key_here
AWS_SECRET_ACCESS_KEY=your_aws_secret_key_here
AWS_DEFAULT_REGION=us-east-1
AWS_S3_BUCKET_NAME=your_legal_raw_pdfs_bucket

# Vector DB
LANCE_DB_PATH=/app/data/.lancedb

# Runtime
ENVIRONMENT=development
```

---

## 🐋 Docker Setup

The project ships a single `Dockerfile` (Python 3.11-slim) that copies the entire workspace and sets `PYTHONPATH` so cross-service imports work without installation. `docker-compose.yml` runs two services from this same image:

| Service | Container | Command | Volumes |
|---|---|---|---|
| `legal_processor_worker` | `legal_processor_worker` | `python3 services/processor/src/worker.py` (default CMD) | `./data`, `./fml-raw-legal-store` |
| `legal_api_server` | `legal_api_server` | `python3 services/api-rag/src/main.py` (overrides CMD) | `./fml-raw-legal-store` |

The API server exposes port `8000` and is set to `restart: always`. The worker is set to `restart: on-failure` so it can exit cleanly after processing a batch.

**Build and run everything:**
```bash
docker-compose up --build
```

**Run only the worker:**
```bash
docker-compose up legal_processor_worker
```

**Run only the API:**
```bash
docker-compose up legal_api_server
```

---

## 🚀 How to Run

### Prerequisites
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # Fill in your API keys
```

### Step 1 — Scrape documents
```bash
python services/scraper/src/main.py
```
Loops through every YAML config, crawls each portal, and saves PDF+JSON pairs to `data/raw/`.

### Step 2 — Process & index
```bash
python services/processor/src/worker.py
```
Picks up everything in `data/raw/`, runs the full classification → chunking → embedding → LanceDB indexing pipeline.

### Step 3 — Test your search
```bash
python services/processor/src/test_search.py
```
Runs a hardcoded test query against LanceDB and prints the RAG-generated answer with source citations.

### Step 4 — Start the API
```bash
python services/api-rag/src/main.py
```
API is live at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

**Example request:**
```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the open access charges under CERC regulations?", "jurisdiction": "CERC"}'
```

---

## 🛡 Built-In Safeguards

**WORM deduplication** — Every PDF is SHA-256 hashed on arrival. The hash is stored on both `LegalDocument` and every `LegalChunk` (as `duplicate_hash`). Before any processing begins, `VectorStore.has_document_hash()` checks whether this hash already exists in the `law_chunks` table. Same document scraped twice → skipped on the second run. Embedding API quota is never wasted on re-processing.

**Atomic cleanup** — Raw staging files (`data/raw/{uid}.pdf` + `.json`) are deleted only after `VectorStore.upsert_chunks()` confirms success. If the internet drops, LlamaParse fails, or LanceDB errors mid-write, the raw files survive and will be picked up on the next worker run.

**Failed download guard** — `generic_collector.py` writes `file_size_bytes: 0` to the JSON when a PDF download fails. `worker.py` reads this field first and exits immediately, before attempting to hash or parse a non-existent PDF.

**Pending flag tracking** — `LegalDocument` carries a boolean `pending_*` flag for every optional metadata field (`pending_date_of_order`, `pending_source_url`, `pending_state`, etc.). When the orchestrator or worker cannot extract a value, the flag is set to `True` and stored in LanceDB alongside the chunks. This makes it trivial to query for documents with incomplete metadata and fix them later without re-processing everything.

**Rate-limit handling** — The embedding loop sleeps 2 seconds between batches of 30 chunks. On a `429` / per-minute RPM error it sleeps 60 seconds and retries. On a daily quota exhaustion error it aborts the current document cleanly (without deleting raw files) and moves to the next one.

**Schema evolution** — `VectorStore.upsert_chunks()` catches `ValueError` on `table.add()` (which LanceDB raises on schema mismatch) and recreates the table with the new schema. This lets you add columns to `LegalChunk` without a manual migration step.

**Config validation at startup** — `config_loader.py` validates every YAML against required keys and known enum values before the scraper touches any network. Bad configs fail loudly at boot, not silently mid-crawl.