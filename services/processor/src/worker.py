# factory_manager.py
import os
import sys
import json
import uuid
import asyncio 
import re
import hashlib

# --- PATH FIX ---
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

from chunker import DocumentProcessor
from embedder import Embedder
from vector_store import VectorStore
# UPDATED: Import the enums to satisfy the new type-safe schema
from models.schema import LegalDocument, LegalObjectType, LegalIssue
from pdf_processor import PDFProcessor

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
    print(f"\n Processing: {os.path.basename(pdf_path)}")
    
    with open(json_path, 'r', encoding='utf-8') as f:
        scraped_data = json.load(f)

    pdf_reader = PDFProcessor(pdf_path)
    raw_text = await pdf_reader.extract_text() 

    if not raw_text.strip():
        print(f" Skipping: No text content found in {pdf_path}")
        return False

    # Generate hash for WORM compliance required by the new schema
    with open(pdf_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()

    legal_meta = enrich_metadata(scraped_data['title'], raw_text)

    # UPDATED: Mapping fields to the new schema requirements
    doc = LegalDocument(
        uid=scraped_data['uid'],
        title=scraped_data['title'],
        content_markdown=raw_text,
        jurisdiction=scraped_data.get('jurisdiction', 'India'),
        category=scraped_data.get('category', legal_meta['category']),
        document_type="Act",
        source_url=scraped_data.get('source_url', 'N/A'), 
        act_name=legal_meta['act_name'],
        act_year=legal_meta['act_year'],
        issuing_authority=scraped_data.get('authority', legal_meta['authority']),
        
        # Mandatory fields added to schema.py (Enums used where required)
        authority=scraped_data.get('authority', "UNKNOWN"),
        legal_object_type=LegalObjectType.JUDGMENT, # Placeholder, will be updated by router
        state=scraped_data.get('state', "CENTRAL"),
        issue_tag_primary=LegalIssue.OTHER,         # Placeholder, will be updated by router
        duplicate_hash=file_hash,
        date_of_order=scraped_data.get('date_of_order', "2024-01-01"),
        version=1
    )

    processor = DocumentProcessor(chunk_size=1500, chunk_overlap=200)
    records = processor.prepare_for_lancedb(doc)

    embedder = Embedder()
    vdb = VectorStore()

    texts = [r.text for r in records]
    # Reduced batch size to stay safer with token limits
    batch_size = 30 

    print(f" Embedding {len(texts)} chunks in batches of {batch_size}...")
    all_vectors = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        
        try:
            vectors = embedder.get_embeddings(batch)
            all_vectors.extend(vectors)
        except Exception as e:
            # Check for Rate Limit Error (429)
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                print(" ⏳ Quota hit! Sleeping 60s to reset Gemini Free Tier limit...")
                await asyncio.sleep(60)
                # Retry once after sleep
                vectors = embedder.get_embeddings(batch)
                all_vectors.extend(vectors)
            else:
                raise e
        
        # Mandatory delay between batches to stay under the 100 RPM limit
        # 1.5s ensures we never exceed ~40 requests per minute
        await asyncio.sleep(1.5) 
    
    for i, record in enumerate(records):
        record.vector = all_vectors[i]

    vdb.upsert_chunks([r.model_dump() for r in records])
    print(f" Indexed in LanceDB: {legal_meta['act_name']}")
    return True

async def run_discovery_and_ingest(limit=None):
    """
    Scans data/raw for pairs.
    :param limit: Number of files to process (None for all).
    """
    raw_dir = os.path.join(project_root, "data", "raw")
    if not os.path.exists(raw_dir):
        print("Folder data/raw not found.")
        return

    metadata_files = [f for f in os.listdir(raw_dir) if f.endswith(".json")]
    
    if not metadata_files:
        print(" No new data in data/raw.")
        return

    # Apply the limit (e.g., process only 1 for testing)
    to_process = metadata_files[:limit] if limit else metadata_files
    print(f" Found {len(metadata_files)} files. Processing {len(to_process)}.")

    for meta_file in to_process:
        json_path = os.path.join(raw_dir, meta_file)
        uid = meta_file.replace(".json", "")
        pdf_path = os.path.join(raw_dir, f"{uid}.pdf")

        if os.path.exists(pdf_path):
            success = await process_discovered_pair(json_path, pdf_path)
            
            if success:
                try:
                    os.remove(json_path)
                    os.remove(pdf_path)
                    print(f" Cleaned up {uid}")
                except Exception as e:
                    print(f" Cleanup error: {e}")
        else:
            print(f" Missing PDF for {uid}")

if __name__ == "__main__":
    # Change to limit=None when you're ready to ingest the whole folder
    asyncio.run(run_discovery_and_ingest(limit=1))