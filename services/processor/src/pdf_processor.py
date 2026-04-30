# raw PDF -> structured text and metadata for RAG pipeline
# PDFProcessor sends local PDFs to LlamaParse, which converts complex regulatory tables into Markdown,
# ensuring RAG doesn't lose data during retrieval.
import os
import asyncio
from llama_parse import LlamaParse, ResultType
from dotenv import load_dotenv

load_dotenv()

class PDFProcessor:
    def __init__(self, file_path: str):
        self.file_path = file_path
        
        self.parser = LlamaParse(
            num_workers=4,           # Faster processing for large legal files
            verbose=True,            # type: ignore
            result_type=ResultType.MD
        )

    async def extract_text(self):
        """Extracts high-quality Markdown from PDF using LlamaParse."""
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"No PDF found at {self.file_path}")
        print(f"Parsing PDF with LlamaParse: {self.file_path}...")
        
        # LlamaParse handles the heavy lifting of OCR and table extraction
        # aload_data is the async version for better performance
        documents = await self.parser.aload_data(self.file_path)
        
        # Combine all pages/documents into one Markdown string
        full_markdown = "\n\n".join([doc.text for doc in documents])
        return full_markdown

    def get_metadata(self):
        """Extracts basic PDF metadata for the vector store."""
        # We keep this lightweight without calling the cloud parser again
        return {
            "source_url": self.file_path,
            "title": os.path.basename(self.file_path),
            "author": "Unknown",
            "jurisdiction": "India",
            "category": "Electricity"  # Defaulting for your Power Grid context
        }