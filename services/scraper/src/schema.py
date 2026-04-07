# ensures every document has a unique ID, which is crucial for RAG retrieval and avoiding duplicates in the vector store.
# The UID can be generated as a hash of the source URL or a combination of title and published date.
# This schema also includes fields for categorization (jurisdiction, category, document type) and metadata (tags, file path in S3) to enhance the filtering capabilities during retrieval.
# helps for easy filtering of data
# if a scraper misses a field, an error will be thrown

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class LegalDocument(BaseModel):
    """Schema for Electricity & Regulatory Infrastructure Data"""
    uid: str = Field(..., description="Unique ID (e.g., hash of URL)")
    title: str
    source_url: str
    jurisdiction: str = Field(..., description="Federal (CERC) or State (MERC, KERC, etc.)")
    category: str = Field(..., description="Power Grid, Renewable, Tariff, etc.")
    document_type: str = Field(..., description="Act, Regulation, Order, or Report")
    published_date: Optional[str] = None
    content_markdown: str
    scraped_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    tags: List[str] = []
    file_path_s3: Optional[str] = None
