# temp test script
# job is to perform "semantic search" and generate a final answer
# easier to run as compared to worker.py
# so this file can be run every time we want to test the search and generation functionality of the RAG pipeline

import os
import sys
from embedder import Embedder
from vector_store import VectorStore
from google import genai 
from dotenv import load_dotenv

# --- PATH FIX: Ensure we can find models if needed, though VectorStore handles its own imports ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
if project_root not in sys.path:
    sys.path.append(project_root)

load_dotenv()

def run_test_query(query_text: str):
    """Run a full RAG pipeline test with the provided query text."""
    print("--- RAG FULL CIRCUIT TEST ---")
    print(f"Question: {query_text}")

    # 1. Initialize tools
    embedder = Embedder()
    vdb = VectorStore()
    # Initialize the Gemini Client for generation
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    # 2. Vectorize the question
    print("Vectorizing query...")
    query_vector = embedder.get_embeddings([query_text])[0]

    # 3. Search LanceDB
    print("Searching LanceDB...")
    results = vdb.query(query_vector, limit=3) 

    # 4. Display Results and Generate Answer
    if not results:
        print("No results found. Did you index the document first?")
    else:
        print(f"\nFound {len(results)} relevant chunks. Synthesizing answer...\n")
        
        # Prepare context for the LLM
        context_text = ""
        for i, row in enumerate(results):
            # FIXED: Using act_name and section_header from the new flat schema
            source_info = f"Source: {row.get('act_name', 'Unknown Document')} | {row.get('section_header', 'General Section')}"
            context_text += f"\n--- {source_info} ---\n{row.get('text', '')}\n"

        # 5. The "R" in RAG: Generation
        # Improved the system instructions slightly to be more authoritative
        prompt = f"""
        You are a precise Legal AI Assistant specializing in Indian Electricity and Solar regulations. 
        Use the provided context to answer the user's question accurately.
        
        If the answer is not contained within the context, state that you do not have enough information in the provided documents.
        
        CONTEXT:
        {context_text}

        QUESTION:
        {query_text}

        ANSWER:
        """


        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

        print("="*40)
        print("FINAL AI ANSWER:")
        print(response.text)
        print("="*40)

        # Optional: Print sources for verification
        print("\nSources used (Metadata Check):")
        for row in results:
            # FIXED: title is now act_name
            name = row.get('act_name', 'Unknown')
            section = row.get('section_header', 'N/A')
            score = row.get('_distance', 0.0)
            print(f"- {name} [{section}] (Score: {score:.4f})")

if __name__ == "__main__":
    # Test with a question related to your Karnataka Solar Policy file
    run_test_query("What are the main objectives of the solar policy?")