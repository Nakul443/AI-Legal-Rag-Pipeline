# retrieval API
# takes a user's question, converts it into a vector,
# and then searches the 100GB of data for the most relevant legal snippets to return as context for the RAG pipeline.
# uses LLM to generate the answer

import lancedb
import os
import google.generativeai as genai
from dotenv import load_dotenv
import sys

# reusing the same embedder from processor
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', 'processor', 'src'))
from embedder import Embedder

load_dotenv()

class RetrievalEngine:
    def __init__(self, db_uri: str | None = None):
        # path logic to find the database from the API service
        if db_uri is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            # Up 3 levels: src -> api-rag -> services -> root
            project_root = os.path.abspath(os.path.join(current_dir, "../../../"))
            db_uri = os.path.join(project_root, "data/index/legal_vdb")

        self.db = lancedb.connect(db_uri) # connect to the LanceDB instance
        self.table_name = "law_chunks" # the table we created in worker.py
        self.embedder = Embedder() # initialize the same embedder to vectorize the query in the same way as the documents were vectorized during indexing
        
        # Configure Gemini for the Generation part
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

        self.llm = genai.GenerativeModel('gemini-2.5-flash') # Updated to a stable version string

    def search(self, query: str, limit: int = 10, jurisdiction: str | None = None):
        """Searches 100GB of data for the most relevant legal snippets."""
        # 1. Convert user question into a vector
        query_vector = self.embedder.get_embeddings([query])[0]
        
        # 2. Open the table
        table = self.db.open_table(self.table_name)
        
        # 3. Build the search query
        search_builder = table.search(query_vector).limit(limit)
        
        # Check if jurisdiction is a string before calling .where()
        if jurisdiction is not None:
            # We use metadata.jurisdiction because of how we structured the chunker
            search_builder = search_builder.where(f"metadata.jurisdiction = '{jurisdiction}'")
            
        # Return as list of dicts instead of Pandas for easier iteration and to avoid column nesting issues
        return search_builder.to_list()

    def ask(self, user_query: str, jurisdiction: str | None = None):
        """The full RAG flow: Search snippets and generate a legal answer."""
        # 1. Get relevant snippets (Using a higher limit to capture more findings)
        results = self.search(user_query, limit=15, jurisdiction=jurisdiction)
        
        if not results:
            return "I couldn't find any relevant legal documents in the database to answer that."

        # 2. Construct the context string
        context_parts = []
        for row in results:
            # Safely get metadata even if nested differently
            meta = row.get('metadata', {})
            source = meta.get('source_url', 'Unknown Source')
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

        # 4. Generate response
        response = self.llm.generate_content(prompt)
        return response.text

if __name__ == "__main__":
    engine = RetrievalEngine()
    
    # a question about CEEW RTS Issue brief
    query = "What are the main findings regarding RTS (Rooftop Solar) in the CEEW brief?"

    print(f"\nQuestion: {query}")
    print("-" * 30)
    
    answer = engine.ask(query)
    print(answer)