# retrieval API
# takes a user's question, converts it into a vector,
# and then searches the 100GB of data for the most relevant legal snippets to return as context for the RAG pipeline.
# uses LLM to generate the answer

import lancedb
import os
import sys
from google import genai 
from dotenv import load_dotenv

# reusing the same embedder from processor
current_dir = os.path.dirname(os.path.abspath(__file__))
# Up 3 levels: src -> api-rag -> services -> root
project_root = os.path.abspath(os.path.join(current_dir, "../../../"))
sys.path.append(os.path.join(project_root, 'services', 'processor', 'src'))

from embedder import Embedder

load_dotenv()

class RetrievalEngine:
    def __init__(self, db_uri: str | None = None):
        # path logic to find the database from the API service
        if db_uri is None:
            db_uri = os.path.join(project_root, "data/index/legal_vdb")

        self.db = lancedb.connect(db_uri) # connect to the LanceDB instance
        self.table_name = "law_chunks" # the table we created in worker.py
        self.embedder = Embedder() # initialize the same embedder to vectorize the query
        
        # Initialize Gemini Client
        # We use the 1.5-flash model for stable, fast legal synthesis
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self.model_name = "gemini-2.5-flash"

    def search(self, search_query: str, limit: int = 10, jurisdiction: str | None = None):
        """Searches 100GB of data for the most relevant legal snippets."""
        # 1. Convert user question into a vector
        query_vector = self.embedder.get_embeddings([search_query])[0]
        
        # 2. Open the table
        table = self.db.open_table(self.table_name)
        
        # 3. Build the search query
        search_builder = table.search(query_vector).limit(limit)
        
        # Fixed: Jurisdiction is now a top-level column in our flattened LanceDB schema
        if jurisdiction:
            search_builder = search_builder.where(f"jurisdiction = '{jurisdiction}'")
            
        # Return as list of dicts to avoid column nesting issues
        return search_builder.to_list()

    def ask(self, user_query: str, jurisdiction: str | None = None):
        """The full RAG flow: Search snippets and generate a legal answer."""
        # 1. Get relevant snippets (Using a higher limit to capture more findings)
        results = self.search(search_query=user_query, limit=15, jurisdiction=jurisdiction)
        
        if not results:
            return "I couldn't find any relevant legal documents in the database to answer that."

        # 2. Construct the context string
        # Metadata is now flattened: 'title' and 'text' are direct keys
        context_parts = []
        for row in results:
            source = row.get('title', 'Unknown Source')
            text = row.get('text', '')
            context_parts.append(f"SOURCE: {source}\nTEXT: {text}")
        
        context_text = "\n\n---\n\n".join(context_parts)

        # 3. Build the professional prompt
        prompt = f"""
                You are a specialized Indian Legal AI. Your task is to extract and summarize findings from the provided document chunks.
                Answer the user's question using ONLY the context provided below. 
                If the context contains tables or lists of state policies, summarize them as "findings."

                CONTEXT:
                {context_text}

                USER QUESTION: 
                {user_query}

                LEGAL ADVICE (Provide a detailed summary and include source citations):
                """

        # 4. Generate response using unified genai client
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt
        )
        return response.text

if __name__ == "__main__":
    engine = RetrievalEngine()
    
    # a question about CEEW RTS Issue brief
    query = "What are the main findings regarding RTS (Rooftop Solar) in the CEEW brief?"

    print(f"\nQuestion: {query}")
    print("-" * 30)
    
    answer = engine.ask(query)
    print(answer)