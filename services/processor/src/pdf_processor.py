import fitz  # PyMuPDF
import os

class PDFProcessor:
    def __init__(self, file_path: str):
        self.file_path = file_path

    def extract_text(self):
        """Extracts text from PDF while preserving basic reading order."""
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"No PDF found at {self.file_path}")

        doc = fitz.open(self.file_path)
        full_text = []

        doc = fitz.open(self.file_path)
        full_text = []
        for page in doc:
            full_text.append(page.get_text("text"))
        doc.close()
        return "\n\n".join(full_text)

    def get_metadata(self):
        """Extracts basic PDF metadata."""
        doc = fitz.open(self.file_path)
        # Fallback to empty dict if metadata is None
        metadata = doc.metadata if doc.metadata is not None else {}
        doc.close()
        
        return {
            "source_url": self.file_path,
            "title": metadata.get("title") or os.path.basename(self.file_path),
            "author": metadata.get("author", "Unknown"),
            "jurisdiction": "India" 
        }