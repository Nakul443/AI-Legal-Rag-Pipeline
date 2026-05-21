# ADDED FUNCTIONALITIES COMMENTS:
# 1. Added validation states and Enum values to align with Section 4.1 for fast-lookup tracking. 
# 2. Added ChallengeStatus Enum to eliminate loose string assignments for 'FINAL', 'UNDER_APPEAL', 'STAYED', and 'REMANDED'. 
# 3. Added boolean flags 'pending_[fieldname]' initialized dynamically to satisfy the Section 4.2 metadata requirement when a field is null at scrape time.
# 4. [FIX] Added Section 4.1 scrape-time fields missing from original: source_domain, scrape_date, pipeline_version, file_size_bytes.
# 5. [FIX] Added WRIT to LegalIssue enum — required by Section 2.2 for HIGH_COURTS/JUDGMENTS sub-folders.
# 6. [FIX] Added pending_source_url flag — source_url is the primary provenance field per Section 4.1 Rule 02.
# 7. [FIX] Expanded Forum enum with

# models/schema.py
# One Source of Truth for the entire Lawyer-RAG-Pipeline.
# Shared by Scraper (Inbound) and Processor (Chunking/Embedding).
# ensures every document has a unique ID, which is crucial for RAG retrieval and avoiding duplicates in the vector store.
# The UID can be generated as a hash of the source URL or a combination of title and published date.
# This schema also includes fields for categorization (jurisdiction, category, document type) and metadata (tags, file path in S3) to enhance the filtering capabilities during retrieval.
# helps for easy filtering of data; if a scraper or processor misses a field, an error will be thrown.
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
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
    SERC_RJ = "SERC_RAJASTHAN"
    SERC_TN = "SERC_TAMIL_NADU"
    # Added as per Phase 1 scope

class LegalObjectType(str, Enum):
    JUDGMENT = "JUDGMENT"
    INTERIM_ORDER = "INTERIM_ORDER"
    REGULATION = "REGULATION"
    AMENDMENT = "AMENDMENT"
    TARIFF_ORDER = "TARIFF_ORDER"
    NOTIFICATION = "NOTIFICATION"
    POLICY = "POLICY"
    # Defined in Data Organisation Guide

class LegalIssue(str, Enum):
    OPEN_ACCESS = "OPEN_ACCESS"
    CHANGE_IN_LAW = "CHANGE_IN_LAW"
    TARIFF = "TARIFF"
    GNA_CONNECTIVITY = "GNA_CONNECTIVITY"
    DSM = "DSM"
    CAPTIVE = "CAPTIVE"
    SCHEDULING_FORECASTING = "SCHEDULING_FORECASTING"
    BANK_GUARANTEE = "BANK_GUARANTEE"
    RPO = "RPO"
    WRIT = "WRIT"  # [FIX] Added: Section 2.2 explicitly lists WRIT as a sub-folder for HIGH_COURTS/JUDGMENTS
    OTHER = "OTHER"
    # Defined in Issue Sub-Folders section

class ChallengeStatus(str, Enum):
    FINAL = "FINAL"
    UNDER_APPEAL = "UNDER_APPEAL"
    STAYED = "STAYED"
    REMANDED = "REMANDED"
    # Defined in Object Tags section

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
    # [FIX] Section 4.1: Scrape-time fields that were missing from original schema.
    # These are populated by generic_collector.save_to_raw() and must be present
    # before the document reaches DataOrchestrator. Without them, Section 4.1's
    # "traceable provenance chain" requirement cannot be satisfied.
    # ──────────────────────────────────────────────────────────────
    source_domain: Optional[str] = None        # e.g., "cercind.gov.in" — domain of the scraped URL
    scrape_date: Optional[str] = None          # ISO timestamp of when the scraper fetched this doc
    pipeline_version: Optional[str] = None     # e.g., "1.0" — version of the ingestion pipeline
    file_size_bytes: Optional[int] = None      # Raw PDF byte size, set after download

    # ──────────────────────────────────────────────────────────────
    # NEW: FindMyLawyer Mandatory Object Tags
    # ──────────────────────────────────────────────────────────────
    industry: Industry = Field(default=Industry.POWER) # D1 
    authority: Forum # D2 
    legal_object_type: LegalObjectType # D3 
    issue_tag_primary: LegalIssue = Field(default=LegalIssue.OTHER) # D4 
    
    date_of_order: Optional[str] = None # YYYY-MM-DD
    effective_date: Optional[str] = None # For Regulations
    state: Optional[str] = Field(default=None, description="CENTRAL/MH/GJ/DL/etc.") # FIXED: Changed from required to Optional to prevent pre-flight instantiation crashes before Orchestrator cleanup
    challenge_status: ChallengeStatus = Field(default=ChallengeStatus.FINAL) #
    version: int = Field(default=1) # WORM Versioning
    duplicate_hash: str # SHA-256 for deduplication

    # Fields for Deterministic Naming 
    parties_petitioner: Optional[str] = None 
    parties_respondent: Optional[str] = None

    # ──────────────────────────────────────────────────────────────
    # NEW: Section 4.2 Automation Verification Layer (Tracking Unpopulated Values)
    # ──────────────────────────────────────────────────────────────
    pending_source_url: bool = Field(default=False)        # [FIX] source_url is Rule 02's primary provenance field — must be tracked
    pending_legal_object_type: bool = Field(default=False)
    pending_date_of_order: bool = Field(default=False)
    pending_state: bool = Field(default=False)
    pending_version: bool = Field(default=False)
    pending_effective_date: bool = Field(default=False)
    pending_issue_tag_primary: bool = Field(default=False)
    pending_parties_petitioner: bool = Field(default=False)
    pending_parties_respondent: bool = Field(default=False)
    pending_challenge_status: bool = Field(default=False)
    # Auto-tags tracking pending states

    @classmethod
    def from_dynamic_input(cls, data: Dict[str, Any]) -> "LegalDocument":
        """
        Dynamic initialization factory that cleanly instantiates the schema model
        from raw unstructured dictionary fields while preserving strict validation.
        """
        return cls(**data)


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
    
    # NEW: Provenance fields for RAG Retrieval
    authority: Forum
    issue_tag_primary: LegalIssue
    
    # Section-Aware Metadata (Critical for Citations)
    section_header: Optional[str] = None # e.g., "Section 135"
    section_title: Optional[str] = None  # e.g., "Theft of Electricity"
    page_number: Optional[int] = None
    
    # [FIX] Forwarded from parent LegalDocument so the LanceDB law_chunks table carries this column.
    # worker.py's WORM pre-flight check queries .where("duplicate_hash == '...'") against this table.
    # Without this field, the column never exists in the schema, the query always returns empty,
    # and deduplication never runs. Every re-scrape of the same document gets re-indexed.
    duplicate_hash: Optional[str] = None # SHA-256 of parent PDF — inherited for WORM dedup queries

    # Enrichment
    summary: Optional[str] = None # A 1-sentence LLM summary of the chunk