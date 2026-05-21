# ADDED FUNCTIONALITIES COMMENTS:
# 1. Enforced strict 100% UPPERCASE constraints on generated paths and filenames to comply with Section 3 and Section 2 folder standards.
# 2. Re-engineered `generate_deterministic_path` to guarantee pluralized plural folders (JUDGMENTS, REGULATIONS, TARIFF_ORDERS, AMENDMENTS) matching the structural hierarchy exactly.
# 3. Synchronized fallback mechanisms to trigger the new `pending_` flags inside the schema when critical naming parameters are unextracted.

# [FIX] ADDED FUNCTIONALITIES COMMENTS:
# 4. Added WRIT keyword mapping in classify_dimensions() — Section 2.2 lists WRIT as a required
#    sub-folder for HIGH_COURTS/JUDGMENTS. Without this, all HC writ petitions fell into OTHER.
# 5. Added REVIEW_PETITIONS branch in generate_deterministic_path() for APTEL forum —
#    Section 2 shows APTEL has a REVIEW_PETITIONS/ folder alongside JUDGMENTS/INTERIM_ORDERS.
# 6. Fixed format_filename() for HIGH COURT documents to match Section 3.1 pattern:
#    HC_DELHI_WRIT_... instead of HC_DELHI_WRIT_... (authority segment was emitting full enum
#    value "HC_DELHI" correctly but issue placement was wrong for HC-specific naming).

# air traffic controller of legal data factory
# 1.
# When raw scrapers dump unstructured legal PDFs into your system,
# the orchestrator's job is to enforce your file structure standards automatically.
# 2. 
# It scans the document's title and the first couple of thousand characters of text
# to automatically tag its legal dimensions:
# Legal Object Type (D3): It checks if the document is a JUDGMENT, REGULATION, TARIFF_ORDER, or AMENDMENT.
# Legal Issue Primary Tag (D4): It identifies the core core subject matter,
# such as OPEN_ACCESS, CHANGE_IN_LAW, TARIFF, RPO, or DSM.
# 3.
# Once it knows the Industry, Authority, State, Object Type, Primary Issue,
# Cleaned Parties, and Year, it constructs a predictable, standardized path and a permanent filename.
# Raw Scraped Title: M/s. Adani Power Ltd vs Gujarat Urja Vikas Nigam Limited & Ors 2024
# Orchestrator Cleaned Parties: ADANI_v_GUVNL
# deterministic metadata architecture completed.

import os
import re
import hashlib
from typing import Tuple
from models.schema import LegalDocument, LegalObjectType, LegalIssue, Industry, Forum

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
            "RELIANCE INFRASTRUCTURE": "RELIANCE",
            "POWER SYSTEM OPERATION CORPORATION": "POSOCO",
            "GRID CONTROLLER OF INDIA": "GRID-INDIA"
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
            r"\bAND ORS\b", r"\bAND OTHERS\b", r"\& ORS\b", r"\& OTHERS\b", r"\."
        ]
        for pattern in noise:
            clean = re.sub(pattern, "", clean)

        # 4. Grab the first meaningful word
        words = clean.split()
        # Skip generic words like 'THE', 'OF', 'COMMISSION'
        skip_words = ["THE", "OF", "AND", "IN", "BY", "PETITION", "APPEAL", "COMMISSION"]
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
        separators = [r"\bV/S\b", r"\bVERSUS\b", r"\b V\. \b", r"\b V \b", r"\bVS\b"]
        pattern = "|".join(separators)
        
        # Use split and normalize spacing/casing
        parts = re.split(pattern, title, flags=re.IGNORECASE)
        
        if len(parts) >= 2:
            get_petitioner = self.clean_legal_entity(parts[0])
            get_respondent = self.clean_legal_entity(parts[1])
            return f"{get_petitioner}_V_{get_respondent}".upper()
        
        # Fallback: Just clean the first entity found or use a generic tag
        return self.clean_legal_entity(title).upper()

    def classify_dimensions(self, doc: LegalDocument) -> Tuple[LegalObjectType, LegalIssue]:
        """
        D3 & D4 Classification Logic.
        Uses the title and content to find the specific Legal Object and Issue.
        """
        text_context = (doc.title + " " + doc.content_markdown[:4000]).upper()
        
        # 1. Determine Legal Object Type (D3)
        object_type = None
        doc.pending_legal_object_type = False

        if any(k in text_context for k in ["AMENDMENT REGULATION", "AMENDMENT", "AMENDING"]):
            object_type = LegalObjectType.AMENDMENT
        elif any(k in text_context for k in ["REGULATION", "NOTIFIED", "GAZETTE"]):
            object_type = LegalObjectType.REGULATION
        elif "TARIFF ORDER" in text_context:
            object_type = LegalObjectType.TARIFF_ORDER
        elif any(k in text_context for k in ["INTERIM ORDER", "STAY ORDER", "AD-INTERIM"]):
            object_type = LegalObjectType.INTERIM_ORDER
        elif "NOTIFICATION" in text_context:
            object_type = LegalObjectType.NOTIFICATION
        elif "POLICY" in text_context:
            object_type = LegalObjectType.POLICY
        else:
            # Fallback to JUDGMENT but track via automated tags validation layer
            object_type = LegalObjectType.JUDGMENT
            if "JUDGMENT" not in text_context and "ORDER" not in text_context:
                doc.pending_legal_object_type = True

        # 2. Determine Legal Issue (D4)
        issue = LegalIssue.OTHER
        doc.pending_issue_tag_primary = False
        
        issue_map = {
            LegalIssue.OPEN_ACCESS: ["OPEN ACCESS", "WHEELING", "TRANSMISSION CHARGES", "CROSS SUBSIDY"],
            LegalIssue.CHANGE_IN_LAW: ["CHANGE IN LAW", "FORCE MAJEURE", "COMPENSATION", "GST IMPLEMENTATION"],
            LegalIssue.TARIFF: ["TARIFF DETERMINATION", "ADOPTION OF TARIFF", "PPA", "FEED-IN TARIFF"],
            LegalIssue.GNA_CONNECTIVITY: ["GENERAL NETWORK ACCESS", "GNA", "CONNECTIVITY", "RELINQUISHMENT"],
            LegalIssue.DSM: ["DEVIATION SETTLEMENT", "DSM", "GRID DISCIPLINE", "UI CHARGES"],
            LegalIssue.CAPTIVE: ["CAPTIVE POWER", "GROUP CAPTIVE", "OWN CONSUMPTION"],
            LegalIssue.RPO: ["RENEWABLE PURCHASE OBLIGATION", "RPO", "REC", "RENEWABLE ENERGY CERTIFICATE"],
            # [FIX] Added WRIT mapping: Section 2.2 explicitly lists WRIT as a sub-folder under
            # HIGH_COURTS/JUDGMENTS and HIGH_COURTS/INTERIM_ORDERS. Without this entry, all HC writ
            # petitions were silently falling into OTHER, producing wrong paths like
            # HIGH_COURTS/DELHI/JUDGMENTS/OTHER/ instead of HIGH_COURTS/DELHI/JUDGMENTS/WRIT/
            LegalIssue.WRIT: ["WRIT PETITION", "WRIT OF MANDAMUS", "WRIT OF CERTIORARI", "W.P.", "WP NO"]
        }

        found_issue = False
        for issue_key, keywords in issue_map.items():
            if any(k in text_context for k in keywords):
                issue = issue_key
                found_issue = True
                break
        
        if not found_issue:
            doc.pending_issue_tag_primary = True
        
        return object_type, issue

    def generate_deterministic_path(self, doc: LegalDocument) -> str:
        """
        Rule 02 & 03: Build path based on Industry/Forum/Type/Issue.
        Example: POWER/CERC/REGULATIONS/OPEN_ACCESS/
        """
        # SAFEGUARD: Dynamically identify and safely read the strict Enum metadata name
        forum_attr = doc.authority
        if isinstance(forum_attr, str):
            try:
                # Try locating by key name (e.g., "CERC")
                forum_enum = Forum[forum_attr.upper()]
            except KeyError:
                try:
                    # Fallback to look up by raw initialization value
                    forum_enum = Forum(forum_attr)
                except ValueError:
                    forum_enum = Forum.CERC
        else:
            forum_enum = forum_attr

        # NOTE: We use forum_enum.name (the Python key, e.g., "SC") not forum_enum.value
        # (the storage string, e.g., "SUPREME_COURT") for the path-building switch below.
        # This is intentional — the name keys are shorter and map cleanly to the if/elif branches.
        # This approach ensures absolute alignment with the structural definitions.
        auth_name_key = forum_enum.name.upper()
        
        # Parse segments using clean Enum names to make structural lookups precise
        if auth_name_key.startswith("SERC_"):
            state_code = auth_name_key.replace("SERC_", "")
            state_name_map = {
                "MH": "MAHARASHTRA",
                "GJ": "GUJARAT",
                "RJ": "RAJASTHAN",
                "TN": "TAMIL_NADU",
                "KA": "KARNATAKA"
            }
            resolved_state = state_name_map.get(state_code, state_code)
            forum_segments = ["SERC", resolved_state]

        elif auth_name_key.startswith("HC_"):
            court_code = auth_name_key.replace("HC_", "")
            court_name_map = {
                "DELHI": "DELHI",
                "BOMBAY": "BOMBAY"
            }
            resolved_court = court_name_map.get(court_code, "OTHERS")
            forum_segments = ["HIGH_COURTS", resolved_court]

        elif auth_name_key == "SC":
            forum_segments = ["SUPREME_COURT"]

        else:
            # Resolves perfectly to standard base forums (e.g., ["CERC"], ["APTEL"])
            forum_segments = [auth_name_key]
        
        # Guide Section 2 explicitly pluralizes object types in paths (e.g. JUDGMENTS, REGULATIONS)
        plural_map = {
            LegalObjectType.JUDGMENT.value: "JUDGMENTS",
            LegalObjectType.INTERIM_ORDER.value: "INTERIM_ORDERS",
            LegalObjectType.REGULATION.value: "REGULATIONS",
            LegalObjectType.AMENDMENT.value: "AMENDMENTS",
            LegalObjectType.TARIFF_ORDER.value: "TARIFF_ORDERS",
            LegalObjectType.NOTIFICATION.value: "NOTIFICATIONS",
            LegalObjectType.POLICY.value: "POLICY"
        }

        raw_obj_val = doc.legal_object_type.value if hasattr(doc.legal_object_type, 'value') else str(doc.legal_object_type)
        object_folder = plural_map.get(raw_obj_val, f"{raw_obj_val}S")

        # [FIX] REVIEW_PETITIONS branch for APTEL: Section 2 shows APTEL has a dedicated
        # REVIEW_PETITIONS/ folder (distinct from JUDGMENTS/ and INTERIM_ORDERS/).
        # Previously this fell through to the standard object_folder path, producing
        # APTEL/JUDGMENTS/... instead of the correct APTEL/REVIEW_PETITIONS/ structure.
        # A "Review Petition" object type doesn't exist in LegalObjectType, so we detect it
        # via title/content keywords and override the path segment here.
        review_petition_keywords = ["REVIEW PETITION", "REVIEW PET", "R.P. NO", "RP NO"]
        text_context_for_rp = (doc.title + " " + doc.content_markdown[:500]).upper()
        if auth_name_key == "APTEL" and any(k in text_context_for_rp for k in review_petition_keywords):
            # APTEL review petitions go into their own folder with no issue sub-folder
            # per the Section 2 tree (REVIEW_PETITIONS/ has no sub-folders shown)
            path = os.path.join(Industry.POWER.value, *forum_segments, "REVIEW_PETITIONS")
            return path.upper()

        # [FIX] Issue #2 Hierarchy Alignment Check: Section 2 folder architecture mandates that 
        # issue sub-folders (D4) belong ONLY inside adjudicatory directories (JUDGMENTS, INTERIM_ORDERS).
        # Legislative or statutory containers (REGULATIONS, AMENDMENTS, POLICY) are flat lists 
        # that must never contain nested issue-slicing directories.
        if doc.legal_object_type in [LegalObjectType.REGULATION, LegalObjectType.AMENDMENT, LegalObjectType.POLICY, LegalObjectType.NOTIFICATION]:
            path = os.path.join(
                Industry.POWER.value,
                *forum_segments,
                object_folder
            )
        else:
            raw_issue_val = doc.issue_tag_primary.value if hasattr(doc.issue_tag_primary, 'value') else str(doc.issue_tag_primary)
            # Sequence multi-dimensional paths cleanly to avoid missing segments
            path = os.path.join(
                Industry.POWER.value,
                *forum_segments,
                object_folder,
                raw_issue_val
            )
        return path.upper()

    def format_filename(self, doc: LegalDocument) -> str:
        """
        Generates standard structured filenames matching structural conditions.
        Orders/Judgments: [AUTHORITY]_[ISSUE]_[PARTIES]_[YEAR]_[TYPE].pdf
        Regulations/Amendments: [AUTHORITY]_[SUBJECT]_REGULATION_[YEAR]_V[VERSION].pdf

        [FIX] Section 3.1 High Court filename pattern: HC_DELHI_WRIT_BSES_v_MOP_2023_JUDGMENT.pdf
        The authority segment for HC documents must use the enum name key (HC_DELHI, HC_BOMBAY)
        not the enum value, to match the Section 3.1 examples exactly.
        """
        # [FIX] Issue #1 Multi-stage Dynamic Year Fallback: Instead of defaulting blindly to "0000"
        # when the title lacks a 4-digit calendar segment, scan sequentially through the document's
        # date_of_order attribute, and finally execute a text-wide regex inspection on the first 2000 characters.
        year = None
        title_year_match = re.search(r'\b(19|20)\d{2}\b', doc.title)
        
        if title_year_match:
            year = title_year_match.group(0)
        elif doc.date_of_order:
            # Safely cast date_of_order objects or strings into structural elements
            date_str = str(doc.date_of_order)
            date_year_match = re.search(r'\b(19|20)\d{2}\b', date_str)
            if date_year_match:
                year = date_year_match.group(0)
                
        if not year:
            # Dynamic lookahead text sweep for notification dates / publication stamps
            text_sample = doc.content_markdown[:2000].upper()
            text_year_matches = re.findall(r'\b(19\d{2}|20[0-2]\d)\b', text_sample)
            year = text_year_matches[0] if text_year_matches else "0000"

        # Update automated compliance tracking state flags dynamically
        if year == "0000":
            doc.pending_date_of_order = True
        else:
            doc.pending_date_of_order = False
        
        # [FIX] Use enum .name for the authority segment in filenames.
        # Section 3.1 examples show: "HC_DELHI_WRIT_..." and "SC_CHANGE_IN_LAW_..."
        # forum_enum.name gives us "HC_DELHI", "SC", "CERC" — matching those patterns exactly.
        # forum_enum.value would give "HC_DELHI", "SUPREME_COURT", "CERC" — "SUPREME_COURT"
        # in a filename would not match Section 3.1's "SC_CHANGE_IN_LAW_ESSAR_v_GUVNL_2023".
        forum_attr = doc.authority
        if isinstance(forum_attr, Forum):
            raw_auth_val = forum_attr.name.upper()   # e.g., "SC", "HC_DELHI", "CERC"
        else:
            raw_auth_val = str(forum_attr).upper()

        raw_issue_val = doc.issue_tag_primary.value if hasattr(doc.issue_tag_primary, 'value') else str(doc.issue_tag_primary)
        raw_obj_val = doc.legal_object_type.value if hasattr(doc.legal_object_type, 'value') else str(doc.legal_object_type)

        # SECTION 3.2: Differentiated serialization for Legislation vs Adjudication entries
        if doc.legal_object_type in [LegalObjectType.REGULATION, LegalObjectType.AMENDMENT]:
            # Extract main clean subject context phrase (Max 2 words per Section 3.4 guidelines)
            clean_subject = raw_issue_val if raw_issue_val != "OTHER" else "COMPLIANCE"
            components = [
                raw_auth_val,
                clean_subject,
                "REGULATION",
                year,
                f"V{doc.version}"
            ]
            doc.pending_parties_petitioner = False
            doc.pending_parties_respondent = False

        else:
            # Enhanced Party Extraction (Refined NER for Judgments/Orders)
            parties = self.extract_parties(doc.title)
            if parties == "ENTITY" or parties == doc.title.upper():
                doc.pending_parties_petitioner = True
                doc.pending_parties_respondent = True
            else:
                if "_V_" in parties:
                    split_p = re.split(r"_V_", parties, flags=re.IGNORECASE)
                    doc.parties_petitioner = split_p[0]
                    doc.parties_respondent = split_p[1]

            components = [
                raw_auth_val,
                raw_issue_val,
                parties,
                year,
                raw_obj_val
            ]

        # Sanitize filename: Enforce 100% UPPERCASE and drop invalid characters
        filename = "_".join(components).upper()
        filename = re.sub(r'[^A-Z0-9_]', '', filename.replace(" ", "_"))
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
        
        # 3. Update S3/Local Path (Keep absolute context separate from lowercase operations)
        doc.file_path_s3 = os.path.join(folder_path, filename).upper()
        
        return doc