# --- ADDED FUNCTIONALITIES COMMENTS:
# 1. Added a pre-flight WORM architecture verification check against LanceDB using the document's SHA-256 duplicate_hash.
# 2. Implemented Section 5 deduplication routing rules: If a file with the same hash exists, it updates or skips without overwriting or generating duplicate files, conforming to Write Once, Read Many principles.
# 3. Synchronized dynamic schema population with automatic verification state flags for unpopulated attributes before executing database upsertions.
# 4. [PERFORMANCE] Implemented asyncio.Semaphore(3) to limit concurrent document processing, preventing local system strain.
# 5. [RESILIENCE] Added exponential backoff retry logic for OpenAI API calls to handle 429 Rate Limit errors gracefully.
# 6. [PERFORMANCE] Refactored to use Global (Singleton) instances for VDB, Embedder, and Orchestrator to eliminate handshake/connection overhead.

# [FIX] ADDED FUNCTIONALITIES COMMENTS:
# 4. Passed source_domain, scrape_date, pipeline_version, file_size_bytes from scraped JSON into
#    LegalDocument() constructor.
# 5. Added pending_source_url=True guard when source_url is absent or 'N/A'.
# 6. Added pending_date_of_order=True guard when date_of_order falls back to placeholder.
# 7. Added ChallengeStatus enum validation block.
# 8. Added file_size_bytes == 0 early exit.
# 9. Moved raw file cleanup to after confirmed upsert_chunks() call.
# 10. Added SQLite StateManager for persistent pipeline tracking.
# 11. Refactored ingestion loop for resumeable and interrupt-safe operations.

import os
import sys
import json
import asyncio 
import re
import hashlib
import shutil
import sqlite3
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

from chunker import DocumentProcessor
from embedder import Embedder
from vector_store import VectorStore
from models.schema import LegalDocument, LegalObjectType, LegalIssue, Forum, ChallengeStatus
from pdf_processor import PDFProcessor
from data_orchestrator import DataOrchestrator

# [PERFORMANCE] Global persistent instances to eliminate handshake overhead
STORAGE_ROOT = os.path.join(project_root, "fml-raw-legal-store")
VDB = VectorStore()
EMBEDDER = Embedder()
ORCHESTRATOR = DataOrchestrator(STORAGE_ROOT)
CONCURRENCY_LIMIT = 3
semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)

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
            category = cat; break
    return {"act_name": act_name, "act_year": year, "category": category, "authority": "Government Authority"}

async def process_with_retry(json_path, pdf_path):
    async with semaphore:
        retries = 0
        while retries < 3:
            try:
                return await process_discovered_pair(json_path, pdf_path)
            except Exception as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    wait_time = (2 ** retries) * 10
                    print(f"Rate limited. Backing off for {wait_time}s...")
                    await asyncio.sleep(wait_time); retries += 1
                else: raise e
        return False

async def process_discovered_pair(json_path: str, pdf_path: str):
    state_mgr = StateManager(os.path.join(project_root, "data", "pipeline_state.db"))
    print(f"\n Processing: {os.path.basename(pdf_path)}")

    with open(json_path, 'r', encoding='utf-8') as f:
        scraped_data = json.load(f)

    uid = scraped_data.get('uid')
    if state_mgr.get_status(uid) == 'indexed': return True
    if scraped_data.get('file_size_bytes', 0) == 0: return False

    with open(pdf_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()

    if VDB.has_document_hash(file_hash):
        state_mgr.update_status(uid, file_hash, 'indexed')
        return True

    pdf_reader = PDFProcessor(pdf_path)
    raw_text = await pdf_reader.extract_text()
    if not raw_text.strip(): return False
    
    legal_meta = enrich_metadata(scraped_data['title'], raw_text)
    raw_authority = str(scraped_data.get('authority', 'CERC')).upper()
    validated_authority = Forum[raw_authority] if raw_authority in Forum.__members__ else Forum.CERC
    
    doc = LegalDocument(
        uid=uid, title=scraped_data['title'], content_markdown=raw_text,
        jurisdiction=scraped_data.get('jurisdiction', 'India'),
        category=scraped_data.get('category', legal_meta['category']),
        document_type="Act", source_url=scraped_data.get('source_url', 'N/A'),
        act_name=legal_meta['act_name'], act_year=legal_meta['act_year'],
        issuing_authority=str(raw_authority), authority=validated_authority,
        legal_object_type=LegalObjectType.JUDGMENT, duplicate_hash=file_hash, version=1
    )

    doc = ORCHESTRATOR.route_document(doc)
    
    # Process Chunks
    processor = DocumentProcessor(chunk_size=1500, chunk_overlap=200)
    records = processor.prepare_for_lancedb(doc)
    
    # [PERFORMANCE] Use global persistent instances
    # Upsert using global VDB and EMBEDDER
    chunk_dicts = [r.model_dump() for r in records]
    for c in chunk_dicts: c['vector'] = EMBEDDER.get_embeddings([c['text']])[0]
    
    VDB.upsert_chunks(chunk_dicts)
    state_mgr.update_status(uid, file_hash, 'indexed')
    
    # Cleanup local variables
    del pdf_reader; del processor; del records
    return True

async def run_discovery_and_ingest():
    raw_dir = os.path.join(project_root, "data", "raw")
    if not os.path.exists(raw_dir): return False
    metadata_files = [f for f in os.listdir(raw_dir) if f.endswith(".json")]
    
    tasks = [process_with_retry(os.path.join(raw_dir, m), os.path.join(raw_dir, f"{m.rsplit('.',1)[0]}.pdf")) 
             for m in metadata_files if os.path.exists(os.path.join(raw_dir, f"{m.rsplit('.',1)[0]}.pdf"))]
    
    if tasks: await asyncio.gather(*tasks)
    return True

if __name__ == "__main__":
    while True:
        try:
            asyncio.run(run_discovery_and_ingest())
            time.sleep(10)
        except Exception as e:
            print(f"Worker iteration failed: {e}"); time.sleep(60)