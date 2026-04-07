# lanceDB manager (lanceDB is the vector database)
# the data manager for the vector store, responsible for saving and retrieving documents,
# and managing the metadata associated with each document.
# It will interface with the vector database (like Pinecone or Weaviate) to store the embeddings and metadata,
# and provide methods for querying the database based on various criteria (e.g., jurisdiction, category, document type).

# makes it easy for the RAG pipeline to search for documents

import lancedb
import os
import pandas as pd
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

    def upsert_chunks(self, records: list):
        """Standardizes and saves chunks into the LanceDB table."""
        df = pd.DataFrame(records)
        
        if self.table_name in self.db.table_names():
            table = self.db.open_table(self.table_name)
            table.add(df)
        else:
            self.db.create_table(self.table_name, data=df)
            
    def query(self, text_vector, limit=5):
        """Searches the database for the most relevant chunks."""
        table = self.db.open_table(self.table_name)
        return table.search(text_vector).limit(limit).to_pandas()