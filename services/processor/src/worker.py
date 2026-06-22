# --- ADDED FUNCTIONALITIES COMMENTS:
# 1. Added a pre-flight WORM architecture verification check against LanceDB using the document's SHA-256 duplicate_hash.
# 2. Implemented Section 5 deduplication routing rules: If a file with the same hash exists, it updates or skips without overwriting or generating duplicate files, conforming to Write Once, Read Many principles.
# 3. Synchronized dynamic schema population with automatic verification state flags for unpopulated attributes before executing database upsertions.

# [FIX] ADDED FUNCTIONALITIES COMMENTS:
# 4. Passed source_domain, scrape_date, pipeline_version, file_size_bytes from scraped JSON into
#    LegalDocument() constructor — these were added to schema.py (Section 4.1) but were never
#    wired through, so all four fields were always None despite the collector writing them.
# 5. Added pending_source_url=True guard when source_url is absent or 'N/A' — source_url is
#    Rule 02's primary provenance field and was the only mandatory Section 4.1 field without a
#    pending flag being set.
# 6. Added pending_date_of_order=True guard when date_of_order falls back to placeholder —
#    previously the hardcoded "2024-01-01" fallback suppressed the pending flag silently.
# 7. Added ChallengeStatus enum validation block matching the Forum enum pattern already in place —
#    raw JSON strings like "FINAL" need explicit enum resolution to avoid Pydantic coercion bugs.
# 8. Added file_size_bytes == 0 early exit: collector sets this to 0 when PDF download failed.
#    Without this guard, worker tried to hash and process a PDF that doesn't exist on disk.
# 9. Moved raw file cleanup to after confirmed upsert_chunks() call — previously cleanup ran
#    after shutil.copy2 but before LanceDB write, so a failed upsert left no raw file and no
#    indexed record (silent data loss). Cleanup now only happens on full pipeline success.
# 10. Added SQLite StateManager for persistent pipeline tracking: tracks file processing status 
#     (pending/processing/indexed/failed) across container restarts to prevent redundant work.
# 11. Refactored ingestion loop: added pre-processing state verification and post-upsert status
#     updates, ensuring the pipeline is now fully resumeable and interrupt-safe.

# factory_manager.py
# Scans the `data/raw` folder and matches every raw `.json` metadata file with its corresponding `.pdf` legal document.
# Extracts the text from the PDF and passes it to the `DataOrchestrator` to auto-tag the exact legal category, issues, and clean party names.
# Splits the extracted legal text into smaller, clean, uniform paragraphs (chunks) so the AI doesn't get overwhelmed by massive pages.
# Converts those text chunks into numerical vectors (embeddings) that capture the underlying semantic legal meaning.
# Saves those vectors along with their matching structured metadata fields directly into LanceDB database table.

import os
import sys
import json
import uuid
import asyncio 
import re
import hashlib
import shutil  # Added for moving files to organized storage
import sqlite3

# Ensure project base directories are appended perfectly across both native host and container environments
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

from chunker import DocumentProcessor
from embedder import Embedder
from vector_store import VectorStore
# UPDATED: Import the enums to satisfy the new type-safe schema
from models.schema import LegalDocument, LegalObjectType, LegalIssue, Forum, ChallengeStatus
from pdf_processor import PDFProcessor
from data_orchestrator import DataOrchestrator  # Import the orchestrator

class StateManager:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("CREATE TABLE IF NOT EXISTS file_states (uid TEXT PRIMARY KEY, hash TEXT, status TEXT)")
        self.conn.commit()

    def get_status(self, uid):
        cursor = self.conn.execute("SELECT status FROM file_states WHERE uid = ?", (uid,))
        row = cursor.fetchone()
        return row[0] if row else None

    def update_status(self, uid, file_hash, status):
        self.conn.execute("INSERT OR REPLACE INTO file_states VALUES (?, ?, ?)", (uid, file_hash, status))
        self.conn.commit()

def enrich_metadata(title: str, text: str) -> dict:
    """Extracts Act Name, Year, and Category from text/title."""
    year_match = re.search(r'\b(19|20)\d{2}\b', title)
    year = int(year_match.group(0)) if year_match else None
    act_name = title.split(str(year))[0].strip(', ') if year else title
    text_sample = (title + " " + text[:2000]).lower()
    category = "General Law"
    
    category_map = {
        "Tariff & Pricing": ["tariff", "pricing", "cost of service", "wheeling"],
        "Renewable Energy": ["solar", "wind", "renewable", "green energy", "mpo", "rec"],
        "Grid & Transmission": ["grid", "transmission", "open access", "connectivity", "load despatch"],
        "Regulatory & Compliance": ["regulation", "compliance", "amendment", "procedure"]
    }
    for cat, keywords in category_map.items():
        if any(kw in text_sample for kw in keywords):
            category = cat
            break
    
    return {
        "act_name": act_name,
        "act_year": year,
        "category": category,
        "authority": "Government Authority" 
    }

async def process_discovered_pair(json_path: str, pdf_path: str):
    # Initialize State Manager
    db_path = os.path.join(project_root, "data", "pipeline_state.db")
    state_mgr = StateManager(db_path)
    
    print(f"\n Processing: {os.path.basename(pdf_path)}")
    
    storage_root = os.path.join(project_root, "fml-raw-legal-store")
    orchestrator = DataOrchestrator(storage_root)
    vdb = VectorStore()

    with open(json_path, 'r', encoding='utf-8') as f:
        scraped_data = json.load(f)

    uid = scraped_data.get('uid')
    # State check
    if state_mgr.get_status(uid) == 'indexed':
        print(f" -> Skipping {uid}: Already indexed.")
        return True

    if scraped_data.get('file_size_bytes', 0) == 0:
        print(f" ⚠️ Skipping {os.path.basename(pdf_path)}: collector recorded file_size_bytes=0 (PDF download failed).")
        return False

    with open(pdf_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()

    # Track as processing
    state_mgr.update_status(uid, file_hash, 'processing')

    if vdb.has_document_hash(file_hash):
        print(f" -> Skipping: {os.path.basename(pdf_path)} (Already fully embedded and stored in LanceDB)")
        state_mgr.update_status(uid, file_hash, 'indexed')
        return True

    try:
        table = vdb.db.open_table(vdb.table_name)
        existing_records = table.search().where(f"duplicate_hash == '{file_hash}'").limit(1).to_list()
        if existing_records:
            print(f" Skipping ingestion: Document hash matches existing tracking entry ({file_hash}).")
            state_mgr.update_status(uid, file_hash, 'indexed')
            return True
    except Exception:
        pass

    pdf_reader = PDFProcessor(pdf_path)
    raw_text = await pdf_reader.extract_text() 
    if not raw_text.strip():
        print(f" Skipping: No text content found in {pdf_path}")
        state_mgr.update_status(uid, file_hash, 'failed')
        return False

    legal_meta = enrich_metadata(scraped_data['title'], raw_text)

    raw_authority = str(scraped_data.get('authority', 'CERC')).upper()
    if raw_authority in Forum.__members__:
        validated_authority = Forum[raw_authority]
    else:
        matched_enum = None
        for member in Forum:
            if member.value == raw_authority:
                matched_enum = member
                break
        validated_authority = matched_enum if matched_enum else Forum.CERC

    pending_state = False if scraped_data.get('state') else True
    pending_effective_date = False if scraped_data.get('effective_date') else True

    raw_challenge = str(scraped_data.get('challenge_status', '')).upper()
    if raw_challenge in ChallengeStatus.__members__:
        validated_challenge_status = ChallengeStatus[raw_challenge]
    else:
        validated_challenge_status = ChallengeStatus.FINAL
    pending_challenge_status = not bool(scraped_data.get('challenge_status'))

    raw_source_url = scraped_data.get('source_url', '')
    pending_source_url = not raw_source_url or raw_source_url == 'N/A'

    raw_date_of_order = scraped_data.get('date_of_order', '')
    pending_date_of_order = not raw_date_of_order or raw_date_of_order == 'N/A'
    date_of_order_value = raw_date_of_order if not pending_date_of_order else None

    doc = LegalDocument(
        uid=uid,
        title=scraped_data['title'],
        content_markdown=raw_text,
        jurisdiction=scraped_data.get('jurisdiction', 'India'),
        category=scraped_data.get('category', legal_meta['category']),
        document_type="Act",
        source_url=raw_source_url or 'N/A',
        act_name=legal_meta['act_name'],
        act_year=legal_meta['act_year'],
        issuing_authority=str(raw_authority),
        authority=validated_authority,
        legal_object_type=LegalObjectType.JUDGMENT, 
        state=scraped_data.get('state', None),
        issue_tag_primary=LegalIssue.OTHER,
        challenge_status=validated_challenge_status,
        duplicate_hash=file_hash,
        date_of_order=date_of_order_value,
        version=1,
        source_domain=scraped_data.get('source_domain', None),
        scrape_date=scraped_data.get('scrape_date', None),
        pipeline_version=scraped_data.get('pipeline_version', None),
        file_size_bytes=scraped_data.get('file_size_bytes', None),
        pending_source_url=pending_source_url,
        pending_date_of_order=pending_date_of_order,
        pending_state=pending_state,
        pending_effective_date=pending_effective_date,
        pending_challenge_status=pending_challenge_status,
    )

    doc = orchestrator.route_document(doc)

    if not isinstance(doc.authority, Forum):
        raw_doc_auth = str(doc.authority).upper()
        if raw_doc_auth in Forum.__members__:
            doc.authority = Forum[raw_doc_auth]
        else:
            doc.authority = Forum.CERC

    if not doc.issue_tag_primary:
        doc.issue_tag_primary = LegalIssue.OTHER

    s3_path = doc.file_path_s3 or "UNCLASSIFIED/UNKNOWN.PDF"
    final_abs_path = os.path.join(storage_root, s3_path)
    os.makedirs(os.path.dirname(final_abs_path), exist_ok=True)
    shutil.copy2(pdf_path, final_abs_path) 
    print(f" -> Organized to: {s3_path}")

    processor = DocumentProcessor(chunk_size=1500, chunk_overlap=200)
    records = processor.prepare_for_lancedb(doc)

    embedder = Embedder()
    texts = [r.text for r in records]
    batch_size = 30 
    all_vectors = []
    quota_exhausted = False

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        while True:
            try:
                vectors = embedder.get_embeddings(batch)
                all_vectors.extend(vectors)
                break
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                    if "quota" in err_msg.lower() or "limit" in err_msg.lower():
                        quota_exhausted = True
                        break
                    await asyncio.sleep(60)
                else:
                    raise e
        if quota_exhausted: break
        await asyncio.sleep(2.0) 
    
    if quota_exhausted or len(all_vectors) != len(records):
        state_mgr.update_status(uid, file_hash, 'failed')
        return False

    for i, record in enumerate(records):
        record.vector = all_vectors[i]

    vdb.upsert_chunks([r.model_dump() for r in records])
    state_mgr.update_status(uid, file_hash, 'indexed')
    print(f" Indexed in LanceDB: {legal_meta['act_name']}")
    return True

async def run_discovery_and_ingest(limit=None):
    raw_dir = os.path.join(project_root, "data", "raw")
    if not os.path.exists(raw_dir): os.makedirs(raw_dir, exist_ok=True)
    try:
        metadata_files = [f for f in os.listdir(raw_dir) if f.endswith(".json")]
    except Exception as e:
        return False
    
    if not metadata_files: return False

    to_process = metadata_files[:limit] if limit else metadata_files
    for meta_file in to_process:
        json_path = os.path.join(raw_dir, meta_file)
        base_name = meta_file.rsplit('.', 1)[0]
        pdf_path = os.path.join(raw_dir, f"{base_name}.pdf")

        if os.path.exists(pdf_path):
            success = await process_discovered_pair(json_path, pdf_path)
            if success:
                try:
                    if os.path.exists(json_path): os.remove(json_path)
                    if os.path.exists(pdf_path): os.remove(pdf_path)
                except Exception as e:
                    print(f" Cleanup error: {e}")
    return True

if __name__ == "__main__":
    print("Starting continuous ingestion worker...")
    while True:
        try:
            processed = asyncio.run(run_discovery_and_ingest(limit=None))
            if not processed:
                import time; time.sleep(30)
            else:
                import time; time.sleep(5)
        except Exception as e:
            print(f"Worker iteration failed: {e}")
            import time; time.sleep(60)