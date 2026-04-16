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

async def process_local_pdf(pdf_path: str):
    print(f"--- Processing PDF: {os.path.basename(pdf_path)} ---")
    
    pdf_reader = PDFProcessor(pdf_path)
    raw_text = await pdf_reader.extract_text() 
    meta = pdf_reader.get_metadata()

    if not raw_text.strip():
        print(f" Warning: No text extracted from {pdf_path}. Skipping.")
        return

    legal_meta = enrich_metadata(meta['title'], raw_text)

    doc = LegalDocument(
        uid=str(uuid.uuid4()),
        title=meta['title'],
        content_markdown=raw_text,
        jurisdiction=meta['jurisdiction'],
        category=legal_meta['category'],
        document_type="Act",
        source_url=meta['source_url'],
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

    vdb.upsert_chunks([r.dict() for r in records])
    print(f"Successfully indexed: {legal_meta['act_name']}")

async def process_and_index_file(file_path: str):
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        doc = LegalDocument(**data)

    if not doc.act_name:
        legal_meta = enrich_metadata(doc.title, doc.content_markdown)
        doc.act_name = legal_meta['act_name']
        doc.act_year = legal_meta['act_year']

    processor = DocumentProcessor() 
    embedder = Embedder() 
    vdb = VectorStore() 

    print(f"Chunking: {doc.title}...")
    records = processor.prepare_for_lancedb(doc)
    
    # FIXED: Changed r['text'] to r.text
    texts = [r.text for r in records]
    vectors = embedder.get_embeddings(texts)

    for i, record in enumerate(records):
        # FIXED: Changed record['vector'] to record.vector
        record.vector = vectors[i]

    print("Upserting to Vector Database...")
    vdb.upsert_chunks([r.dict() for r in records])
    print(f"Successfully indexed: {doc.uid}")

if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "../../../"))
    
    test_filename = "Electricity_Act_2003.pdf"
    target_file = os.path.join(project_root, "data", "raw", test_filename)

    if os.path.exists(target_file):
        _, extension = os.path.splitext(target_file)
        if extension.lower() == ".pdf":
            asyncio.run(process_local_pdf(target_file))
        elif extension.lower() == ".json":
            asyncio.run(process_and_index_file(target_file))
    else:
        print(f"ERROR: File not found at {target_file}")