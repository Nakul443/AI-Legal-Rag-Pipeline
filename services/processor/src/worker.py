# the "factory manager" of the pipeline
# takes a raw file, sends it through the Chunker, then the Embedder, and finally stores it in LanceDB.
# This file will orchestrate the entire process of taking a raw document, breaking it into chunks,
# generating embeddings for those chunks, and then saving everything to the vector database.
# It will also handle any necessary metadata management
# and ensure that the data is properly formatted for efficient retrieval during the RAG pipeline.
# Load → Chunk → Embed → Store.


# this file won't run every time.
# only run it when new laws are passed or there's a significant change in data

import os
import sys
import json
import uuid
import asyncio # Added to handle async PDF processing

# --- PATH FIX: Ensures it can find chunker, embedder, etc. ---
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from chunker import DocumentProcessor
from embedder import Embedder
from vector_store import VectorStore
from schema import LegalDocument
from pdf_processor import PDFProcessor

async def process_local_pdf(pdf_path: str): # Made this async
    print(f"--- Processing PDF: {os.path.basename(pdf_path)} ---")
    
    # 1. Extract
    pdf_reader = PDFProcessor(pdf_path)
    # Changed to await because LlamaParse is async
    raw_text = await pdf_reader.extract_text() 
    meta = pdf_reader.get_metadata()

    if not raw_text.strip():
        print(f"⚠️ Warning: No text extracted from {pdf_path}. Skipping.")
        return

    # 2. Schema Wrap
    doc = LegalDocument(
        uid=str(uuid.uuid4()),
        title=meta['title'],
        content_markdown=raw_text,
        jurisdiction=meta['jurisdiction'],
        category="General Law", 
        document_type="PDF",
        source_url=meta['source_url']
    )

    # 3. Chunk
    processor = DocumentProcessor(chunk_size=1000, chunk_overlap=200)
    records = processor.prepare_for_lancedb(doc)
    print(f"Created {len(records)} chunks.")

    # 4. Embed in Batches (Safety for 100+ pages)
    embedder = Embedder()
    vdb = VectorStore()
    
    texts = [r['text'] for r in records]
    all_vectors = []
    batch_size = 50 # Process 50 chunks at a time
    
    print(f"Generating embeddings for {len(texts)} chunks in batches of {batch_size}...")
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        vectors = embedder.get_embeddings(batch)
        all_vectors.extend(vectors)
        print(f"Progress: {len(all_vectors)}/{len(texts)}")
    
    # 5. Attach & Store
    for i, record in enumerate(records):
        record['vector'] = all_vectors[i]

    vdb.upsert_chunks(records)
    print(f"Successfully indexed PDF: {meta['title']}")

def process_and_index_file(file_path: str):
    # 1. Load the Scraped Data
    with open(file_path, 'r') as f:
        data = json.load(f)
        doc = LegalDocument(**data)

    # 2. Initialize Tools
    processor = DocumentProcessor() # chunking
    embedder = Embedder() # embedding into the vector database
    vdb = VectorStore() # vector database manager

    # 3. Chunk the Legal Text
    print(f"Chunking: {doc.title}...")
    records = processor.prepare_for_lancedb(doc)
    
    # 4. Generate Embeddings for all chunks at once
    print(f"Generating Embeddings for {len(records)} chunks...")
    texts = [r['text'] for r in records]
    vectors = embedder.get_embeddings(texts)

    # 5. Attach vectors to records
    for i, record in enumerate(records):
        record['vector'] = vectors[i]

    # 6. Save to LanceDB
    print("Upserting to Vector Database...")
    vdb.upsert_chunks(records)
    print(f"Successfully indexed: {doc.uid}")

if __name__ == "__main__":
    # 1. Get the absolute path of the directory where worker.py lives
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 2. Go up 3 levels to the root, then into data/raw/
    # src -> processor -> services -> root
    project_root = os.path.abspath(os.path.join(current_dir, "../../../"))
    pdf_to_test = os.path.join(project_root, "data", "raw", "my_legal_doc.pdf")
    
    target_file = os.path.abspath(os.path.join(project_root, "data/raw/my_legal_doc.pdf"))

    print("--- Starting Local Indexing Test ---")
    print(f"Targeting: {pdf_to_test}") # Debug print to see where it's looking
    
    if os.path.exists(pdf_to_test):
        # 1. Get the extension (e.g., '.pdf' or '.json')
        _, extension = os.path.splitext(target_file)
        
        # 2. Branch based on file type
        if extension.lower() == ".pdf":
            print("Detected PDF. Running PDF pipeline...")
            # Run the async function using asyncio
            asyncio.run(process_local_pdf(target_file))
            
        elif extension.lower() == ".json":
            print("Detected JSON. Running Scraper-data pipeline...")
            process_and_index_file(target_file)
    else:
        print(f"ERROR: File not found at {pdf_to_test}")
        print(f"Check your directory: Current path is {os.getcwd()}")