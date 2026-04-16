# logic that will take a 100-page legal document, break it into small "chunks," and prepare it for embedding.

import os
import sys
import re
from typing import List
from models.schema import LegalDocument, LegalChunk

# --- PATH FIX: Ensures it can find schema.py in the same directory ---
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

class DocumentProcessor:
    def __init__(self, chunk_size: int = 1500, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        # REGEX: Matches "Section 1", "Sec. 1", "Article 5", "Chapter II", etc.
        self.section_pattern = re.compile(r'(?i)^(Section|Sec\.|Article|Chapter|Clause)\s+(\d+|[IVXLC]+)', re.MULTILINE)

    def chunk_text(self, text: str) -> List[dict]:
        """
        Splits text by Section/Article headers rather than arbitrary character counts.
        Returns a list of dictionaries containing the text and the identified header.
        """
        if not text:
            return []
            
        final_chunks = []
        
        # 1. Identify all header positions
        matches = list(self.section_pattern.finditer(text))
        
        if not matches:
            # Fallback to standard paragraph splitting if no legal headers found
            paragraphs = text.split("\n\n")
            return [{"text": p, "header": "General"} for p in paragraphs if p.strip()]

        # 2. Slice text between headers
        for i in range(len(matches)):
            start_index = matches[i].start()
            end_index = matches[i+1].start() if i + 1 < len(matches) else len(text)
            
            section_content = text[start_index:end_index].strip()
            header_text = matches[i].group(0) # e.g., "Section 135"

            # Sub-chunking for massive sections
            if len(section_content) > self.chunk_size:
                sub_chunks = [section_content[j:j + self.chunk_size] for j in range(0, len(section_content), self.chunk_size - self.chunk_overlap)]
                for sc in sub_chunks:
                    final_chunks.append({"text": sc, "header": header_text})
            else:
                final_chunks.append({"text": section_content, "header": header_text})
        
        return final_chunks

    def prepare_for_lancedb(self, doc: LegalDocument) -> List[LegalChunk]:
        """Prepares LegalChunk objects for the Vector Database with Metadata Enrichment."""
        raw_chunks = self.chunk_text(doc.content_markdown)
        legal_chunks = []
        
        for index, item in enumerate(raw_chunks):
            chunk_text = item["text"]
            header = item["header"]

            if not chunk_text.strip():
                continue

            # --- CONTEXT INJECTION ---
            # Prepending context for the Vector model's "understanding"
            enriched_text = f"ACT: {doc.act_name or doc.title}\nSECTION: {header}\n\n{chunk_text}"

            # Creating an actual LegalChunk instance (clears the Pylance warning)
            chunk_obj = LegalChunk(
                chunk_id=f"{doc.uid}_{index}",
                parent_id=doc.uid,
                text=enriched_text,
                jurisdiction=doc.jurisdiction,
                act_name=doc.act_name or doc.title,
                section_header=header
            )
            
            legal_chunks.append(chunk_obj)
            
        return legal_chunks