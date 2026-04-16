# temp test script
# job is to perform "semantic search" and generate a final answer
# easier to run as compared to worker.py
# so this file can be run every time we want to test the search and generation functionality of the RAG pipeline

import os
from embedder import Embedder
from vector_store import VectorStore
# Added for the generation phase
from google import genai 
from dotenv import load_dotenv

load_dotenv()

def run_test_query(query_text: str):
    print(f"--- RAG FULL CIRCUIT TEST ---")
    print(f"Question: {query_text}")

    # 1. Initialize tools
    embedder = Embedder()
    vdb = VectorStore()
    # Initialize the Gemini Client for generation
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    # 2. Vectorize the question
    # We wrap in a list because our embedder expects a list of strings
    print("Vectorizing query...")
    query_vector = embedder.get_embeddings([query_text])[0]

    # 3. Search LanceDB
    print("Searching LanceDB...")
    results = vdb.query(query_vector, limit=3) # Increased limit to 3 for better context

    # 4. Display Results and Generate Answer
    if not results:
        print("No results found. Did you index the document first?")
    else:
        print(f"\nFound {len(results)} relevant chunks. Synthesizing answer...\n")
        
        # Prepare context for the LLM
        context_text = ""
        for i, row in enumerate(results):
            context_text += f"\n--- Context Chunk {i+1} ---\n{row.get('text', '')}\n"

        # 5. The "R" in RAG: Generation
        prompt = f"""
        You are a precise Legal AI Assistant. Use the provided context to answer the user's question.
        If the answer isn't in the context, say you don't know.
        
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
        print("\nSources used:")
        for row in results:
            print(f"- {row.get('title', 'Unknown Source')} (Score: {row.get('_distance', 'N/A'):.4f})")

if __name__ == "__main__":
    # Test with a question related to your Karnataka Solar Policy file
    run_test_query("What are the main objectives of the solar policy?")