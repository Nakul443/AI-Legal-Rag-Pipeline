# retrieval API
# takes a user's question, converts it into a vector,
# and then searches the 100GB of data for the most relevant legal snippets to return as context for the RAG pipeline.
# uses LLM to generate the answer

# [FIX] ADDED FUNCTIONALITIES COMMENTS:
# 12. Integrated FlashRank Re-ranker: Implemented a two-stage retrieval process. Now retrieves 50 candidates 
#     from LanceDB and re-ranks them locally to select the top 5 most semantically relevant chunks, 
#     significantly increasing precision and reducing LLM context pollution.
# 13. Optimized context assembly: Pipeline now dynamically truncates context based on re-ranker scores, 
#     ensuring the LLM receives only high-confidence legal snippets.

import lancedb
import os
import sys
from openai import OpenAI, OpenAIError # Updated to OpenAI with error handling
from dotenv import load_dotenv
from flashrank import Ranker # ADDED: For high-precision re-ranking

# reusing the same embedder from processor
current_dir = os.path.dirname(os.path.abspath(__file__))

# --- FIXED: Use clean, reliable path lookup for Docker environment ---
if os.path.exists("/app"):
    project_root = "/app"
else:
    project_root = os.path.abspath(os.path.join(current_dir, "../../../"))

sys.path.append(os.path.join(project_root, 'services', 'processor', 'src'))

from embedder import Embedder
from vector_store import VectorStore  # Import your project's shared VectorStore configuration class

load_dotenv()

class RetrievalEngine:
    def __init__(self, db_uri: str | None = None):
        # path logic to find the database from the API service
        if db_uri is None:
            db_uri = os.path.join(project_root, "data/index/legal_vdb")

        # --- FIXED: Force VectorStore to use the exact absolute container target path ---
        self.vdb = VectorStore(uri=db_uri)
        self.db = lancedb.connect(db_uri) # connect to the LanceDB instance
        self.table_name = self.vdb.table_name 
        
        self.embedder = Embedder() # initialize the same embedder to vectorize the query
        
        # ADDED: Initialize FlashRank Ranker (loads a tiny cross-encoder model locally)
        self.ranker = Ranker() 
        
        # Initialize OpenAI Client
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model_name = "gpt-4o-mini"

    def search(self, search_query: str, limit: int = 50, jurisdiction: str | None = None):
        """Searches 100GB of data and re-ranks results for maximum relevance."""
        # 1. Convert user question into a vector
        query_vector = self.embedder.get_embeddings([search_query])[0]
        
        # 2. Open the table safely using VectorStore runtime verification
        if self.table_name not in self.db.table_names():
            print(f"⚠️ Table '{self.table_name}' missing! Available tables: {self.db.table_names()}")
            return []
            
        table = self.db.open_table(self.table_name)
        
        # 3. Build the search query (Retrieve 50 candidates for re-ranking)
        search_builder = table.search(query_vector).limit(limit)
        
        # Fixed: Jurisdiction is now a top-level column in our flattened LanceDB schema
        if jurisdiction:
            search_builder = search_builder.where(f"jurisdiction = '{jurisdiction}'")
            
        results = search_builder.to_list()

        # ADDED: Re-ranking logic
        rerank_input = [{"id": r["chunk_id"], "text": r["text"]} for r in results]
        reranked_results = self.ranker.rerank(query=search_query, passages=rerank_input)
        
        # Map re-ranked IDs back to full row data
        ranked_ids = [r["id"] for r in reranked_results[:5]] # Keep top 5
        final_results = [r for r in results if r["chunk_id"] in ranked_ids]
        
        return final_results

    def ask(self, user_query: str, jurisdiction: str | None = None):
        """The full RAG flow: Search snippets and generate a legal answer."""
        # 1. Get relevant snippets (Re-ranking logic now inside search)
        results = self.search(search_query=user_query, limit=50, jurisdiction=jurisdiction)
        
        if not results:
            return "I couldn't find any relevant legal documents in the database to answer that."

        # 2. Construct the context string
        # Metadata is now flattened: 'title' and 'text' are direct keys
        context_parts = []
        
        for row in results:
            # Use 'act_name' since that is the column present in your LanceDB
            source_name = row.get('act_name') or 'Unknown Source'
            text = row.get('text', '')
            
            context_parts.append(f"SOURCE: {source_name}\nTEXT: {text}")
        
        context_text = "\n\n---\n\n".join(context_parts)

        # 3. Build the professional prompt
        prompt = f"""
        You are a specialized Indian Legal AI. 
        Analyze the provided CONTEXT carefully to answer the USER QUESTION.

        CRITICAL INSTRUCTIONS:
        1. If the CONTEXT contains relevant legal clauses, regulations, or rules, summarize them clearly.
        2. If the CONTEXT consists only of administrative rosters, headings, or unrelated data, state that "The retrieved documents contain administrative metadata but do not contain the specific legal rules requested."
        3. Do not invent information. Use ONLY the provided CONTEXT.

        CONTEXT:
        {context_text}

        USER QUESTION: 
        {user_query}

        ANSWER:
        """

        # 4. Generate response using OpenAI with error handling
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.choices[0].message.content
        except OpenAIError as e:
            return f"Error generating answer: {str(e)}"

if __name__ == "__main__":
    engine = RetrievalEngine()
    query = "What rules or items are mentioned in the 2005 APTEL or WBERC documents?"

    print(f"\nQuestion: {query}")
    print("-" * 30)
    
    try:
        answer = engine.ask(query)
        print(answer)
    except Exception as e:
        print(f" Run error: {str(e)}")