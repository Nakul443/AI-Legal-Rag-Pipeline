# file to ingest general-purpose PDFs into the general_chunks vector store
# Compute the file's SHA-256 hash and append the user_id to form a scoped duplicate hash f"{user_id}_{file_hash}".
# This ensures duplicate checking is scoped per-user.

# Initialize VectorStore(table_name="general_chunks") and check has_document_hash() first to prevent redundant parsing and embedding.

# Reuse PDFProcessor to parse the file using LlamaParse.

# Reuse DocumentProcessor to chunk the text
# (using identical chunk configuration of chunk size 1500 and chunk overlap 200 as the legal path).

# Generate embeddings using Embedder.

# Assemble a plain dict for each chunk according to the plain schema
# (with text, vector, title, source, page, user_id, upload_date, and duplicate_hash),
# and write them into the database using VectorStore.upsert_chunks().

import asyncio
import hashlib
import os
from datetime import datetime

from services.processor.src.chunker import DocumentProcessor
from services.processor.src.embedder import Embedder
from services.processor.src.pdf_processor import PDFProcessor
from services.processor.src.vector_store import VectorStore


async def ingest_general_pdf(file_path: str, user_id: str, source_name: str) -> bool:
    """
    Ingests a general-purpose PDF synchronously/on-demand into the general_chunks vector store.
    No classification steps are run; LlamaParse extracts the raw markdown.
    
    Returns:
        bool: True if ingestion was successful (or skipped as a duplicate), False otherwise.
    """
    if not os.path.exists(file_path):
        print(f"Error: PDF not found at {file_path}")
        return False

    # 1. Compute file hash and build scoped duplicate hash
    with open(file_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()
    
    # Scoped to user_id so users don't collide if they upload the same PDF
    scoped_hash = f"{user_id}_{file_hash}"

    # 2. Initialize VectorStore with table name "general_chunks"
    vdb = VectorStore(table_name="general_chunks")
    
    if vdb.has_document_hash(scoped_hash):
        print(f"Document {source_name} already indexed for user {user_id}. Skipping...")
        return True

    # 3. Extract text using PDFProcessor (LlamaParse extraction)
    pdf_reader = PDFProcessor(file_path)
    raw_text = await pdf_reader.extract_text()
    if not raw_text.strip():
        print(f"No text extracted from {file_path}")
        return False

    # 4. Chunk text using DocumentProcessor
    processor = DocumentProcessor(chunk_size=1500, chunk_overlap=200)
    raw_chunks = processor.chunk_text(raw_text)
    if not raw_chunks:
        print("No chunks generated")
        return False

    # 5. Generate Embeddings using Embedder
    embedder = Embedder()
    texts = [c["text"] for c in raw_chunks]
    embeddings = embedder.get_embeddings(texts)

    # 6. Assemble chunks matching the plain general schema and upsert
    upload_date = datetime.utcnow().isoformat()
    records = []
    
    for idx, (chunk_item, vector) in enumerate(zip(raw_chunks, embeddings)):
        # Try to extract page if available in chunk headers or default to None
        header = chunk_item.get("header", "")
        # Since plain schema is lightweight, build plain dict:
        record = {
            "text": chunk_item["text"],
            "vector": vector,
            "title": source_name,
            "source": os.path.basename(file_path),
            "page": None,  # Page is not reliably parsed inline by chunker
            "user_id": user_id,
            "upload_date": upload_date,
            "duplicate_hash": scoped_hash
        }
        records.append(record)

    vdb.upsert_chunks(records)
    print(f"Successfully ingested {len(records)} chunks for user {user_id} into general_chunks.")
    return True
