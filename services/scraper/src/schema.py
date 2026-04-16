# ensures every document has a unique ID, which is crucial for RAG retrieval and avoiding duplicates in the vector store.
# The UID can be generated as a hash of the source URL or a combination of title and published date.
# This schema also includes fields for categorization (jurisdiction, category, document type) and metadata (tags, file path in S3) to enhance the filtering capabilities during retrieval.
# helps for easy filtering of data
# if a scraper misses a field, an error will be thrown

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class LegalDocument(BaseModel):
    """Schema for Electricity & Regulatory Infrastructure Data (The Parent File)"""
    uid: str = Field(..., description="Unique ID (e.g., hash of URL)")
    title: str
    source_url: str
    jurisdiction: str = Field(..., description="Federal (CERC) or State (MERC, KERC, etc.)")
    category: str = Field(..., description="Power Grid, Renewable, Tariff, etc.")
    document_type: str = Field(..., description="Act, Regulation, Order, or Report")
    published_date: Optional[str] = None
    content_markdown: str # The full raw text from LlamaParse
    scraped_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    tags: List[str] = []
    file_path_s3: Optional[str] = None
    
    # NEW: Legal metadata for higher accuracy
    act_name: Optional[str] = None
    act_year: Optional[int] = None
    issuing_authority: Optional[str] = None # e.g., "Ministry of Power"

class LegalChunk(BaseModel):
    """Schema for individual vector search units (The Child Chunks)"""
    chunk_id: str = Field(..., description="Unique hash for the specific chunk")
    parent_id: str = Field(..., description="UID of the parent LegalDocument")
    text: str # The actual content of the section
    vector: Optional[List[float]] = None # To be filled by the embedder
    
    # Contextual Metadata (Copied from parent for easy filtering in Vector DB)
    jurisdiction: str
    act_name: str
    
    # Section-Aware Metadata (Critical for Citations)
    section_header: Optional[str] = None # e.g., "Section 135"
    section_title: Optional[str] = None  # e.g., "Theft of Electricity"
    page_number: Optional[int] = None
    
    # Enrichment
    summary: Optional[str] = None # A 1-sentence LLM summary of the chunk