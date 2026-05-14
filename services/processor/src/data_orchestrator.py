import os
import re
import hashlib
from typing import Tuple
from models.schema import LegalDocument, LegalObjectType, LegalIssue, Industry

class DataOrchestrator:
    def __init__(self, base_storage_path: str):
        self.base_path = base_storage_path
        # Map of common long names to standard abbreviations for filenames
        self.abbreviation_map = {
            "GUJARAT URJA VIKAS NIGAM": "GUVNL",
            "MAHARASHTRA STATE ELECTRICITY DISTRIBUTION": "MSEDCL",
            "POWER GRID CORPORATION": "PGCIL",
            "NATIONAL THERMAL POWER": "NTPC",
            "TRANSMISSION CORPORATION": "TRANSCO",
            "TATA POWER": "TATA",
            "RELIANCE INFRASTRUCTURE": "RELIANCE"
        }

    def clean_legal_entity(self, entity_str: str) -> str:
        """
        Refined NER: Removes legal suffixes, honorifics, and returns a clean 1-word identifier.
        """
        # 1. Standardize to Uppercase
        clean = entity_str.upper()
        
        # 2. Check for known large entities first
        for full_name, abbr in self.abbreviation_map.items():
            if full_name in clean:
                return abbr

        # 3. Remove Honorifics & Suffixes
        noise = [
            r"\bM/S\b", r"\bSHRI\b", r"\bSMT\b", r"\bPVT\b", r"\bLTD\b", 
            r"\bLIMITED\b", r"\bPRIVATE\b", r"\bCORP\b", r"\bCORPORATION\b",
            r"\bAND ORS\b", r"\bAND OTHERS\b", r"\."
        ]
        for pattern in noise:
            clean = re.sub(pattern, "", clean)

        # 4. Grab the first meaningful word
        words = clean.split()
        # Skip generic words like 'THE', 'OF', 'COMMISSION'
        skip_words = ["THE", "OF", "AND", "IN", "BY", "PETITION", "APPEAL"]
        meaningful_words = [w for w in words if w not in skip_words]

        return meaningful_words[0] if meaningful_words else "ENTITY"

    def extract_parties(self, title: str) -> str:
        """
        Splits title based on 'V/S', 'VERSUS', 'V.', etc.
        """
        # Handle Suo Motu cases
        if "SUO MOTU" in title.upper():
            return "SUO_MOTU"

        # Look for various "Versus" separators
        separators = [r"\bV/S\b", r"\bVERSUS\b", r"\b V\. \b", r"\b V \b"]
        pattern = "|".join(separators)
        
        parts = re.split(pattern, title, flags=re.IGNORECASE)
        
        if len(parts) >= 2:
            petitioner = self.clean_legal_entity(parts[0])
            respondent = self.clean_legal_entity(parts[1])
            return f"{petitioner}_v_{respondent}"
        
        # Fallback: Just clean the first entity found or use a generic tag
        return self.clean_legal_entity(title)

    def classify_dimensions(self, doc: LegalDocument) -> Tuple[LegalObjectType, LegalIssue]:
        """
        D3 & D4 Classification Logic.
        Uses the title and content to find the specific Legal Object and Issue.
        """
        text_context = (doc.title + " " + doc.content_markdown[:2000]).upper()
        
        # 1. Determine Legal Object Type (D3)
        object_type = LegalObjectType.JUDGMENT # Default
        if any(k in text_context for k in ["REGULATION", "NOTIFIED", "GAZETTE"]):
            object_type = LegalObjectType.REGULATION
        elif "TARIFF ORDER" in text_context:
            object_type = LegalObjectType.TARIFF_ORDER
        elif "AMENDMENT" in text_context:
            object_type = LegalObjectType.AMENDMENT

        # 2. Determine Legal Issue (D4)
        issue = LegalIssue.OTHER
        issue_map = {
            LegalIssue.OPEN_ACCESS: ["OPEN ACCESS", "WHEELING", "TRANSMISSION CHARGES"],
            LegalIssue.CHANGE_IN_LAW: ["CHANGE IN LAW", "FORCE MAJEURE", "COMPENSATION"],
            LegalIssue.TARIFF: ["TARIFF DETERMINATION", "ADOPTION OF TARIFF", "PPA"],
            LegalIssue.RPO: ["RENEWABLE PURCHASE OBLIGATION", "RPO", "REC"],
            LegalIssue.DSM: ["DEVIATION SETTLEMENT", "DSM", "GRID DISCIPLINE"]
        }

        for issue_key, keywords in issue_map.items():
            if any(k in text_context for k in keywords):
                issue = issue_key
                break
        
        return object_type, issue

    def generate_deterministic_path(self, doc: LegalDocument) -> str:
        """
        Rule 02 & 03: Build path based on Industry/Forum/Type/Issue.
        Example: POWER/CERC/REGULATIONS/OPEN_ACCESS/
        """
        # Mapping Dim 2 (Forum) - Ensures SERCs are grouped by state
        forum_folder = doc.authority.upper()
        if "SERC" in forum_folder and doc.state != "CENTRAL":
            forum_folder = f"SERC/{doc.state}"

        path = os.path.join(
            Industry.POWER.value,
            forum_folder,
            doc.legal_object_type.value,
            doc.issue_tag_primary.value
        )
        return path

    def format_filename(self, doc: LegalDocument) -> str:
        """
        Generates the standard filename: 
        [AUTHORITY]_[ISSUE]_[PARTIES]_[YEAR]_[TYPE].pdf
        """
        # Clean title for year and parties
        year_match = re.search(r'\b(19|20)\d{2}\b', doc.title)
        year = year_match.group(0) if year_match else "0000"
        
        # Enhanced Party Extraction (Refined NER)
        parties = self.extract_parties(doc.title)

        # Build components as per naming convention
        components = [
            doc.authority.upper(),
            doc.issue_tag_primary.value,
            parties,
            year,
            doc.legal_object_type.value
        ]

        # Sanitize filename: Replace spaces with underscores and remove non-alphanumeric except underscores
        filename = "_".join(components)
        filename = re.sub(r'[^a-zA-Z0-9_]', '', filename.replace(" ", "_"))
        return f"{filename}.pdf"

    def route_document(self, doc: LegalDocument) -> LegalDocument:
        """Main entry point to prepare document for storage."""
        # 1. Classify
        obj_type, issue = self.classify_dimensions(doc)
        doc.legal_object_type = obj_type
        doc.issue_tag_primary = issue
        
        # 2. Pathing
        folder_path = self.generate_deterministic_path(doc)
        filename = self.format_filename(doc)
        
        # 3. Update S3/Local Path
        doc.file_path_s3 = os.path.join(folder_path, filename)
        
        return doc