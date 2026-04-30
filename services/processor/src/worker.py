# the "factory manager" of the pipeline
# takes a raw file, sends it through the Chunker, then the Embedder, and finally stores it in LanceDB.
# This file will orchestrate the entire process of taking a raw document, breaking it into chunks,
# generating embeddings for those chunks, and then saving everything to the vector database.
# It will also handle any necessary metadata management
# and ensure that the data is properly formatted for efficient retrieval during the RAG pipeline.
# Load → Chunk → Embed → Store.


# this file won't run every time.
# only run it when new laws are passed or there's a significant change in data


# update:
# before chunking we will extract the title from pdf to store it

import os
import sys
import json
import uuid
import asyncio 
import re

# --- PATH FIX: Ensures it can find chunker, embedder, etc. ---
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

from chunker import DocumentProcessor
from embedder import Embedder
from vector_store import VectorStore
from models.schema import LegalDocument
from pdf_processor import PDFProcessor

def enrich_metadata(title: str, text: str) -> dict:
    """
    METADATA ENRICHER: 
    Extracts the official Act Name, Year, and Category from the title or top of the text.
    """
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
        "authority": "Central Government" 
    }

async def process_discovered_pair(json_path: str, pdf_path: str):
    """
    Internal helper to process a single JSON/PDF pair.
    """
    print(f"--- Processing: {os.path.basename(pdf_path)} ---")
    
    # Load the scraped metadata first
    with open(json_path, 'r', encoding='utf-8') as f:
        scraped_data = json.load(f)

    pdf_reader = PDFProcessor(pdf_path)
    raw_text = await pdf_reader.extract_text() 
    # Use existing PDF metadata if needed, or fallback to scraped data
    meta = pdf_reader.get_metadata()

    if not raw_text.strip():
        print(f" Warning: No text extracted from {pdf_path}. Skipping.")
        return False

    legal_meta = enrich_metadata(scraped_data['title'], raw_text)

    doc = LegalDocument(
        uid=scraped_data['uid'],
        title=scraped_data['title'],
        content_markdown=raw_text,
        jurisdiction=scraped_data['jurisdiction'],
        category=scraped_data.get('category', legal_meta['category']),
        document_type="Act",
        source_url=scraped_data['source_url'],
        act_name=legal_meta['act_name'],
        act_year=legal_meta['act_year'],
        issuing_authority=legal_meta['authority']
    )

    processor = DocumentProcessor(chunk_size=1500, chunk_overlap=200)
    records = processor.prepare_for_lancedb(doc)
    print(f"Created {len(records)} section-aware chunks.")

    embedder = Embedder()
    vdb = VectorStore()
    
    # FIXED: Changed r['text'] to r.text
    texts = [r.text for r in records]
    all_vectors = []
    batch_size = 50 
    
    print(f"Generating embeddings for {len(texts)} chunks in batches of {batch_size}...")
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        vectors = embedder.get_embeddings(batch)
        all_vectors.extend(vectors)
    
    for i, record in enumerate(records):
        # FIXED: Changed record['vector'] to record.vector
        record.vector = all_vectors[i]

    vdb.upsert_chunks([r.model_dump() for r in records])
    print(f"Successfully indexed: {legal_meta['act_name']}")
    return True

async def run_discovery_and_ingest():
    """
    Scans data/raw for UUID-based pairs and purges them after ingestion.
    """
    raw_dir = os.path.join(project_root, "data", "raw")
    if not os.path.exists(raw_dir):
        print("Data/raw directory not found.")
        return

    # Find all .json files (the metadata anchors)
    metadata_files = [f for f in os.listdir(raw_dir) if f.endswith(".json")]
    
    if not metadata_files:
        print("No new files in data/raw to process.")
        return

    for meta_file in metadata_files:
        json_path = os.path.join(raw_dir, meta_file)
        # Scraper saves files as {uid}.json and {uid}.pdf
        uid = meta_file.replace(".json", "")
        pdf_path = os.path.join(raw_dir, f"{uid}.pdf")

        if os.path.exists(pdf_path):
            success = await process_discovered_pair(json_path, pdf_path)
            
            # --- SCALE PROTECTION: PURGE ---
            if success:
                try:
                    os.remove(json_path)
                    os.remove(pdf_path)
                    print(f" Purged local files for {uid} to save disk space.")
                except Exception as e:
                    print(f" Cleanup error: {e}")
        else:
            print(f" Skipping {uid}: Corresponding PDF not found.")

if __name__ == "__main__":
    # Now calls the discovery logic instead of hardcoded filenames
    asyncio.run(run_discovery_and_ingest())