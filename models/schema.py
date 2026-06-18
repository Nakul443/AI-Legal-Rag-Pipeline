# models/schema.py
# One Source of Truth for the entire Lawyer-RAG-Pipeline.
# Shared by Scraper (Inbound) and Processor (Chunking/Embedding).
# Ensures every document has a unique ID, which is crucial for RAG retrieval and avoiding duplicates in the vector store.
# The UID can be generated as a hash of the source URL or a combination of title and published date.
# This schema also includes fields for categorization (jurisdiction, category, document type) and metadata (tags, file path in S3) to enhance the filtering capabilities during retrieval.
# Helps for easy filtering of data; if a scraper or processor misses a field, an error will be thrown.

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
    SUPREME_COURT = "SUPREME_COURT"
    HC_DELHI = "HC_DELHI"
    HC_BOMBAY = "HC_BOMBAY"
    SERC_MH = "SERC_MAHARASHTRA"
    SERC_GJ = "SERC_GUJARAT"
    SERC_KA = "SERC_KARNATAKA"
    SERC_RJ = "SERC_RAJASTHAN"
    SERC_TN = "SERC_TAMIL_NADU"
    # [FIX] Completed Forum enum expansion matrix safely to avoid unassigned field token failures
    MERC = "MERC"
    KERC = "KERC"
    TNERC = "TNERC"
    UPERC = "UPERC"
    WBERC = "WBERC"
    DERC = "DERC"
    BERC = "BERC"
    HERC = "HERC"
    BEE = "BEE"
    MOP = "MOP"

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
        Converts null elements automatically to satisfy Section 4.2 tracking checks.
        """
        # Ensure pending field trackers mirror incoming null states accurately
        raw_src = data.get('source_url', '')
        data['pending_source_url'] = not raw_src or raw_src == 'N/A'
        data['pending_legal_object_type'] = data.get('legal_object_type') is None or data.get('legal_object_type') == "N/A"
        
        raw_doo = data.get('date_of_order', '')
        data['pending_date_of_order'] = not raw_doo or raw_doo == 'N/A'
        
        data['pending_state'] = data.get('state') is None or data.get('state') == "N/A"
        data['pending_version'] = data.get('version') is None
        data['pending_effective_date'] = data.get('effective_date') is None or data.get('effective_date') == "N/A"
        data['pending_issue_tag_primary'] = data.get('issue_tag_primary') is None or data.get('issue_tag_primary') == "OTHER"
        data['pending_parties_petitioner'] = data.get('parties_petitioner') is None or data.get('parties_petitioner') == "N/A"
        data['pending_parties_respondent'] = data.get('parties_respondent') is None or data.get('parties_respondent') == "N/A"
        data['pending_challenge_status'] = data.get('challenge_status') is None

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