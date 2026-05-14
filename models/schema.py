# models/schema.py
# One Source of Truth for the entire Lawyer-RAG-Pipeline.
# Shared by Scraper (Inbound) and Processor (Chunking/Embedding).
# ensures every document has a unique ID, which is crucial for RAG retrieval and avoiding duplicates in the vector store.
# The UID can be generated as a hash of the source URL or a combination of title and published date.
# This schema also includes fields for categorization (jurisdiction, category, document type) and metadata (tags, file path in S3) to enhance the filtering capabilities during retrieval.
# helps for easy filtering of data; if a scraper or processor misses a field, an error will be thrown.

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum

# NEW: Enums to enforce the "Non-Negotiable" naming and tagging rules 
class Industry(str, Enum):
    POWER = "POWER"
    TELECOM = "TELECOM" # Phase 2+ 

class Forum(str, Enum):
    CERC = "CERC"
    APTEL = "APTEL"
    SC = "SUPREME_COURT"
    HC_DELHI = "HC_DELHI"
    HC_BOMBAY = "HC_BOMBAY"
    SERC_MH = "SERC_MAHARASHTRA"
    SERC_GJ = "SERC_GUJARAT"
    SERC_KA = "SERC_KARNATAKA"
    # Added as per Phase 1 scope [cite: 152]

class LegalObjectType(str, Enum):
    JUDGMENT = "JUDGMENT"
    INTERIM_ORDER = "INTERIM_ORDER"
    REGULATION = "REGULATION"
    AMENDMENT = "AMENDMENT"
    TARIFF_ORDER = "TARIFF_ORDER"
    NOTIFICATION = "NOTIFICATION"
    POLICY = "POLICY"
    # Defined in Data Organisation Guide [cite: 99]

class LegalIssue(str, Enum):
    OPEN_ACCESS = "OPEN_ACCESS"
    CHANGE_IN_LAW = "CHANGE_IN_LAW"
    TARIFF = "TARIFF"
    GNA_CONNECTIVITY = "GNA_CONNECTIVITY"
    DSM = "DSM"
    CAPTIVE = "CAPTIVE"
    RPO = "RPO"
    OTHER = "OTHER"
    # Defined in Issue Sub-Folders section [cite: 103]

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
    
    # NEW: Legal metadata for higher accuracy and rich citations
    act_name: Optional[str] = None
    act_year: Optional[int] = None
    issuing_authority: Optional[str] = None # e.g., "Ministry of Power"

    # ──────────────────────────────────────────────────────────────
    # NEW: FindMyLawyer Mandatory Object Tags
    # ──────────────────────────────────────────────────────────────
    industry: Industry = Field(default=Industry.POWER) # D1 
    authority: Forum # D2 
    legal_object_type: LegalObjectType # D3 
    issue_tag_primary: LegalIssue = Field(default=LegalIssue.OTHER) # D4 
    
    date_of_order: Optional[str] = None # YYYY-MM-DD [cite: 132]
    effective_date: Optional[str] = None # For Regulations [cite: 132]
    state: str = Field(..., description="CENTRAL/MH/GJ/DL/etc.") # [cite: 132]
    challenge_status: str = Field(default="FINAL") # FINAL/STAYED/etc. [cite: 132]
    version: int = Field(default=1) # WORM Versioning [cite: 132, 136]
    duplicate_hash: str # SHA-256 for deduplication [cite: 132, 148]

    # Fields for Deterministic Naming 
    parties_petitioner: Optional[str] = None 
    parties_respondent: Optional[str] = None

class LegalChunk(BaseModel):        
    """Schema for individual vector search units (The Child Chunks)"""
    chunk_id: str = Field(..., description="Unique hash for the specific chunk")
    parent_id: str = Field(..., description="UID of the parent LegalDocument")
    text: str # The actual content of the section (including injected context)
    vector: Optional[List[float]] = None # To be filled by the embedder
    
    # Contextual Metadata (Copied from parent for easy filtering in Vector DB)
    jurisdiction: str
    act_name: str
    category: Optional[str] = None
    
    # NEW: Provenance fields for RAG Retrieval [cite: 126]
    authority: Forum
    issue_tag_primary: LegalIssue
    
    # Section-Aware Metadata (Critical for Citations)
    section_header: Optional[str] = None # e.g., "Section 135"
    section_title: Optional[str] = None  # e.g., "Theft of Electricity"
    page_number: Optional[int] = None
    
    # Enrichment
    summary: Optional[str] = None # A 1-sentence LLM summary of the chunk