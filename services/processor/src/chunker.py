# logic that will take a 100-page legal document, break it into small "chunks," and prepare it for embedding.

# [FIX] ADDED FUNCTIONALITIES COMMENTS:
# 1. Added duplicate_hash field forwarding in prepare_for_lancedb(): each LegalChunk now carries
#    the parent document's SHA-256 hash. This is required because worker.py's WORM pre-flight check
#    queries LanceDB with .where("duplicate_hash == '...'") — if the column doesn't exist in the
#    stored chunks, that query always returns empty and deduplication never runs.
# 2. Added category forwarding: LegalChunk.category is Optional in schema but was never populated,
#    losing the category enrichment computed in worker.py's enrich_metadata() for every chunk.
# 3. Integrated LangChain RecursiveCharacterTextSplitter: replaced manual sub-chunking slicing with 
#    a recursive character splitter (800 char size, 100 char overlap). This ensures legal 
#    continuity and prevents sentence fragmentation at chunk boundaries.

import os
import sys
import re
from typing import List
from langchain.text_splitter import RecursiveCharacterTextSplitter
from models.schema import LegalDocument, LegalChunk
# --- PATH FIX: Ensures it can find schema.py in the same directory ---
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

class DocumentProcessor:
    def __init__(self, chunk_size: int = 800, chunk_overlap: int = 100):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        # REGEX: Matches "Section 1", "Sec. 1", "Article 5", "Chapter II", etc.
        self.section_pattern = re.compile(r'(?i)^(Section|Sec\.|Article|Chapter|Clause)\s+(\d+|[IVXLC]+)', re.MULTILINE)
        
        # ADDED: Initialize the Recursive Splitter
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            length_function=len,
        )

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
            for p in paragraphs:
                if p.strip():
                    # ADDED: Apply recursive splitter to long paragraphs
                    sub_texts = self.splitter.split_text(p)
                    for st in sub_texts:
                        final_chunks.append({"text": st, "header": "General"})
            return final_chunks

        # 2. Slice text between headers
        for i in range(len(matches)):
            start_index = matches[i].start()
            end_index = matches[i+1].start() if i + 1 < len(matches) else len(text)
            
            section_content = text[start_index:end_index].strip()
            header_text = matches[i].group(0) # e.g., "Section 135"

            # ADDED: Use recursive splitter for sub-chunking instead of manual slicing
            sub_chunks = self.splitter.split_text(section_content)
            for sc in sub_chunks:
                final_chunks.append({"text": sc, "header": header_text})
        
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

            # FIXED: Forward mandatory validation fields from parent doc down to LegalChunk
            chunk_obj = LegalChunk(
                chunk_id=f"{doc.uid}_{index}",
                parent_id=doc.uid,
                text=enriched_text,
                jurisdiction=doc.jurisdiction,
                act_name=doc.act_name or doc.title,
                section_header=header,
                
                # Mandatory metadata forwarded to prevent Pydantic missing field validation errors
                authority=doc.authority,
                issue_tag_primary=doc.issue_tag_primary,

                # [FIX] Forward category from parent: enrich_metadata() in worker.py computes a
                # category ("Tariff & Pricing", "Renewable Energy", etc.) and stores it on the
                # LegalDocument, but it was never copied to chunks. Now every chunk carries it
                # for vector DB filtering.
                category=doc.category,

                # [FIX] Forward duplicate_hash from parent document to every chunk.
                # worker.py's WORM pre-flight check does:
                #   table.search().where(f"duplicate_hash == '{file_hash}'").limit(1)
                # This queries the LanceDB law_chunks table. If chunks don't carry duplicate_hash,
                # the column never exists in the table schema and the query silently returns empty
                # on every run — meaning no document is ever detected as a duplicate, the WORM
                # deduplication guarantee (Section 5 & Rule 7) never fires, and every re-scrape
                # of the same document gets re-embedded and re-indexed.
                duplicate_hash=doc.duplicate_hash,
            )
            
            legal_chunks.append(chunk_obj)
            
        return legal_chunks