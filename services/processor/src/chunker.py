# logic that will take a 100-page legal document, break it into small "chunks," and prepare it for embedding.

import os
import sys
import uuid
from typing import List

# --- PATH FIX: Ensures it can find schema.py in the same directory ---
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from schema import LegalDocument

class DocumentProcessor:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_text(self, text: str) -> List[str]:
        """Splits long text into overlapping chunks for better RAG context."""
        chunks = []
        if not text:
            return chunks
            
        # Ensure we start at 0 and move by the effective size (size - overlap)
        step = self.chunk_size - self.chunk_overlap
        for i in range(0, len(text), step):
            chunk = text[i : i + self.chunk_size]
            chunks.append(chunk)
            
            # Break if we've reached the end of the string to avoid empty chunks
            if i + self.chunk_size >= len(text):
                break
        return chunks

    def prepare_for_lancedb(self, doc: LegalDocument):
        """Prepares metadata and chunks for the Vector Database with Context Injection."""
        chunks = self.chunk_text(doc.content_markdown)
        records = []
        
        for index, chunk in enumerate(chunks):
            # --- CONTEXT INJECTION START ---
            # We prepend the title and organization directly to the text.
            # This ensures that even if 'CEEW' isn't in the raw text of the table,
            # the chunk is still mathematically related to 'CEEW' and 'Solar'.
            context_header = f"DOCUMENT: {doc.title}\nORGANIZATION: CEEW\nJURISDICTION: {doc.jurisdiction}\n\n"
            enriched_text = context_header + chunk
            # --- CONTEXT INJECTION END ---

            records.append({
                "id": f"{doc.uid}_{index}",
                "doc_id": doc.uid,
                "text": enriched_text, # Use the enriched version for the vector search
                "metadata": {
                    "title": doc.title,
                    "jurisdiction": doc.jurisdiction,
                    "category": doc.category,
                    "source_url": doc.source_url
                }
            })
        return records