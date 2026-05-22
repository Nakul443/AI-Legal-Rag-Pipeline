# lanceDB manager (lanceDB is the vector database)
# the data manager for the vector store, responsible for saving and retrieving documents,
# and managing the metadata associated with each document.
# It will interface with the vector database to store the embeddings and metadata,
# and provide methods for querying the database based on various criteria (e.g., jurisdiction, category, document type).

# makes it easy for the RAG pipeline to search for documents

import lancedb
import os
import pandas as pd
import numpy as np # Added for vector type casting
from enum import Enum  # Added to check and serialize the new schema enums safely
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

class VectorStore:
    def __init__(self, uri: Optional[str] = None):
        # In production, this URI will be an S3 path: "s3://bucket-name/index"
        
        # --- FIXED: Use absolute path to project root ---
        if uri is None:
            # Get the directory where this file lives
            current_dir = os.path.dirname(os.path.abspath(__file__))
            # Go up 3 levels to reach the project root: src -> processor -> services -> root
            project_root = os.path.abspath(os.path.join(current_dir, "../../../"))
            uri = os.path.join(project_root, "data/index/legal_vdb")
        
        # Ensure the directory exists before connecting
        os.makedirs(os.path.dirname(uri), exist_ok=True)
        
        self.db = lancedb.connect(uri)
        self.table_name = "law_chunks"

    def has_document_hash(self, file_hash: str) -> bool:
        """
        Simple check to see if a file hash is already in the database.
        Returns True if found, False if not.
        """
        # If the table does not exist yet, the document is definitely not inside
        if self.table_name not in self.db.table_names():
            return False
            
        try:
            table = self.db.open_table(self.table_name)
            # Look for even just one text chunk matching this file signature
            results = table.search().where(f"duplicate_hash == '{file_hash}'").limit(1).to_list()
            return len(results) > 0
        except Exception:
            # If any database error happens, safely assume it is not found
            return False

    def upsert_chunks(self, records: list):
        """Standardizes and saves chunks into the LanceDB table."""
        processed_records = []
        for r in records:
            
            # Create a copy to avoid mutating the original dict
            flat_record = r.copy()
            
            # Ensure vector is float32 for LanceDB performance
            if "vector" in flat_record and flat_record["vector"] is not None:
                flat_record["vector"] = np.array(flat_record["vector"], dtype=np.float32)
            
            # FIX: Convert any Enum objects (like LegalObjectType or LegalIssue) to their string values
            # so LanceDB can index and filter them as standard text columns.
            for key, value in flat_record.items():
                if isinstance(value, Enum):
                    flat_record[key] = value.value

            processed_records.append(flat_record)

        df = pd.DataFrame(processed_records)
        
        if self.table_name in self.db.table_names():
            table = self.db.open_table(self.table_name)
            # Try to add data; if the schema has changed (e.g. added 'section_header'), catch the error
            try:
                table.add(df)
            except ValueError as e:
                print(f"Schema mismatch detected: {e}")
                print(f"Re-creating table '{self.table_name}' with new legal metadata schema...")
                self.db.create_table(self.table_name, data=df, mode='overwrite')
        else:
            # Creating table with mode='overwrite' ensures fresh schema if needed
            self.db.create_table(self.table_name, data=df, mode='overwrite')
            
    def query(self, text_vector, limit=5, filter_str: Optional[str] = None):
        """Searches the database for the most relevant chunks."""
        if self.table_name not in self.db.table_names():
            return [] # Return empty list if no data exists yet
            
        table = self.db.open_table(self.table_name)
        
        # Enhanced query logic to support SQL-like filtering (e.g., jurisdiction = 'CERC')
        query_builder = table.search(text_vector)
        
        if filter_str:
            query_builder = query_builder.where(filter_str)
            
        return query_builder.limit(limit).to_list()

# One-Line Flow:
# VectorStore manages the local LanceDB instance, flattening record metadata and converting embeddings into NumPy arrays for high-speed semantic search.