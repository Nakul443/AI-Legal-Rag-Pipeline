# 📜 FindMyLawyer - Legal RAG Ingestion Pipeline

This system is a specialized, production-grade legal document ingestion pipeline. It automatically collects regulatory PDFs (from agencies like CERC, CEA, MNRE), parses their complex layouts, dynamically organizes them by legal categories, and builds an optimized semantic vector database for AI-powered legal research.

---

## 🛠 What Exactly This System Does

1. **Discovers & Scrapes:** Collects raw legal metadata (`.json`) and court order documents (`.pdf`).
2. **Filters & Protects:** Instantly drops failed or corrupted downloads and checks unique file hashes so it **never duplicates** work or wastes your AI API limits.
3. **Classifies & Routes:** Reads the text to automatically determine the Industry, Court/Forum, Document Type, and Primary Legal Issue, moving files into a perfect, deterministic folder structure.
4. **Intelligently Chunks:** Breaks massive legal pages into clean paragraphs without cutting clauses or definitions in half.
5. **Vectors & Stores:** Generates embedding vectors using the Gemini API and saves both the math coordinates and rich metadata into a high-performance, local **LanceDB** database.

---

## 📂 System File Structure & Core Components

Here is how your codebase is laid out, along with exactly what each crucial file is responsible for:

```text
├── data/                            <-- LanceDB index and any local data assets
├── fml-raw-legal-store/             <-- Raw scraped legal files landing zone (.json + .pdf)
│
├── models/
│   └── schema.py                    <-- Enforces strict, type-safe rules for legal data
│
├── services/
│   ├── api-rag/                     <-- (Upcoming) REST API layer for querying the RAG pipeline
│   └── processor/
│       └── src/
│           ├── chunker.py           <-- The text-cutter (breaks text into smart pieces)
│           ├── data_orchestrator.py <-- The gatekeeper (routes, names, and versions files)
│           ├── embedder.py          <-- The translator (turns text into numbers via Gemini)
│           ├── pdf_processor.py     <-- The reader (extracts text cleanly out of PDFs)
│           ├── s3_manager.py        <-- The cloud handler (manages S3 storage operations)
│           ├── test_search.py       <-- Quick script to test vector search queries
│           ├── vector_store.py      <-- The database manager (saves and queries LanceDB)
│           └── worker.py            <-- THE MAIN CHEF (coordinates the entire workflow)
│
├── scraper/
│   ├── configs/                     <-- YAML config files for each scraping portal
│   └── src/
│       ├── collectors/
│       │   └── generic_collector.py <-- Reusable scraper logic for government web portals
│       └── utils/
│           └── config_loader.py     <-- Loads and parses scraper YAML configurations
│       └── main.py                  <-- Entry point to kick off the scraping process
│
├── venv/                            <-- Python virtual environment (not committed to git)
├── .env                             <-- Secret keys and environment variables
├── .gitignore
├── README.md
└── requirements.txt                 <-- All Python dependencies
```

### 🧠 The Important Files Explained

- **`worker.py` (The Orchestrator):** This is the main engine running your backend processing loop. It scans your raw store, triggers the guards, calls the chunker/embedder, updates the database, and safely cleans up your files only after a confirmed success to prevent data loss.

- **`data_orchestrator.py` (The Smart Router):** It acts as a gatekeeper. It inspects document metadata and text to classify them across 4 dimensions (*Industry → Forum → Object Type → Legal Issue*) and builds clean, predictable storage paths.

- **`models/schema.py` (The Rulebook):** Contains Pydantic models and Enums (`Forum`, `ChallengeStatus`, etc.). It ensures that raw text strings from scrapers are strictly validated before hitting the database, catching bugs silently before they corrupt data.

- **`chunker.py` (The Chunker):** Implements structural chunking so important legal definitions and sub-clauses stay grouped together instead of getting randomly sliced up by generic character counts.

- **`embedder.py` (The Gemini Messenger):** Handles communication with the Google API, managing batch transfers and smart retry delays if you hit minute-by-minute rate limits.

- **`vector_store.py` (The DB Connection):** Manages local connections to LanceDB and provides standard hooks to insert or locate documents quickly.

- **`s3_manager.py` (The Cloud Handler):** Manages upload and retrieval of legal documents to/from AWS S3, acting as the long-term storage layer beyond local disk.

- **`generic_collector.py` (The Web Scraper):** Reusable scraper that navigates government portals, downloads PDFs, and saves accompanying metadata JSON files into `fml-raw-legal-store/`.

- **`main.py` (The Scraper Entry Point):** Kicks off the scraping process by loading portal configs and dispatching the collector across all configured sources.

---

## 🔄 The Data Lifecycle Flow

```
[ Step 1: Scraper Portal ] ──► Saves Raw (.json + .pdf) ──► [ data/raw/ ]
                                                                  │
                                                       (worker.py detects pair)
                                                                  ▼
[ LanceDB Check ] ◄─── Skips if duplicate SHA-256 hash exists ◄───┤
                                                                  ▼
[ data_orchestrator.py ] ──► Determines proper paths ─────────────┤
                                                                  ▼
[ chunker.py & embedder.py ] ──► Chunks text & calls Gemini API ──┤
                                                                  ▼
[ Final Destination ] ──► Saved permanently in LanceDB & Storage Vault!
```

---

## 🐋 Docker Setup (Coming Soon)

> **NOTE:** This section is a placeholder. We will be adding a `Dockerfile` here next to containerize our Playwright web browsers, Python runtime dependencies, and system environments so the entire pipeline runs flawlessly on AWS ECS Fargate.

---

## 🚀 How to Run the Pipeline (Locally on WSL)

### 1. Run the Scraper

To kick off document discovery and download raw PDFs + metadata from configured government portals:

```bash
python scraper/src/main.py
```

### 2. Ingest & Process Discovered Files

To scan `fml-raw-legal-store/`, run classification routing, generate vectors, index them into LanceDB, and clean up staging areas:

```bash
python services/processor/src/worker.py
```

### 3. Search Your Database

To run a test vector search query against your indexed LanceDB:

```bash
python services/processor/src/test_search.py
```

---

## 🎁 Extra Features Built-In

- **Free-Tier Budget Guardian:** Implements smart `asyncio.sleep` cooldown thresholds to keep your execution safe under standard API restrictions.
- **Atomic Fail-Safe Operations:** If your internet drops or LanceDB fails halfway through a document, the original files are *never* deleted from your drive, preventing silent data loss.
- **WORM Architecture Compliance:** Uses SHA-256 physical document hashing to enforce "Write Once, Read Many" principles, meaning identical files are never processed twice.