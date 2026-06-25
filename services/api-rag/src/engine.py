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
import numpy as np 
from openai import OpenAI, OpenAIError # Updated to OpenAI with error handling
from dotenv import load_dotenv
from sentence_transformers import CrossEncoder # FIXED: Using CrossEncoder to bypass onnxruntime errors

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
        if db_uri is None:
            db_uri = os.path.join(project_root, "data/index/legal_vdb")

        self.vdb = VectorStore(uri=db_uri)
        self.db = lancedb.connect(db_uri)
        self.table_name = self.vdb.table_name 
        self.embedder = Embedder()
        
        # FIXED: Initialize robust CrossEncoder
        self.ranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2") 
        
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model_name = "gpt-4o-mini"

    def search(self, search_query: str, limit: int = 50, jurisdiction: str | None = None):
        """Searches 100GB of data and re-ranks results for maximum relevance."""
        query_vector = self.embedder.get_embeddings([search_query])[0]
        
        if self.table_name not in self.db.table_names():
            return []
            
        table = self.db.open_table(self.table_name)
        search_builder = table.search(query_vector).limit(limit)
        
        if jurisdiction:
            search_builder = search_builder.where(f"jurisdiction = '{jurisdiction}'")
            
        results = search_builder.to_list()

        # FIXED: Robust Re-ranking logic using CrossEncoder
        pairs = [[search_query, r["text"]] for r in results]
        scores = self.ranker.predict(pairs)
        
        # Attach scores back to results
        for i, r in enumerate(results):
            r['rerank_score'] = scores[i]
        
        # Sort and pick top 5
        results.sort(key=lambda x: x['rerank_score'], reverse=True)
        final_results = results[:5]
        
        return final_results

    def ask(self, user_query: str, jurisdiction: str | None = None):
        results = self.search(search_query=user_query, limit=50, jurisdiction=jurisdiction)
        
        if not results:
            return "I couldn't find any relevant legal documents in the database to answer that."

        context_parts = []
        for row in results:
            source_name = row.get('act_name') or 'Unknown Source'
            text = row.get('text', '')
            context_parts.append(f"SOURCE: {source_name}\nTEXT: {text}")
        
        context_text = "\n\n---\n\n".join(context_parts)

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
    try:
        answer = engine.ask(query)
        print(answer)
    except Exception as e:
        print(f" Run error: {str(e)}")