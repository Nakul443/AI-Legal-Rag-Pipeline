# temp test script
# job is to perform "semantic search"
# easier to run as compared to worker.py
# so this file can be run every time we want to test the search functionality of the RAG pipeline

import os
from embedder import Embedder
from vector_store import VectorStore

def run_test_query(query_text: str):
    print(f"--- RAG SMOKE TEST ---")
    print(f"Question: {query_text}")

    # 1. Initialize tools
    embedder = Embedder()
    vdb = VectorStore()

    # 2. Vectorize the question
    # We wrap in a list because our embedder expects a list of strings
    print("Vectorizing query...")
    query_vector = embedder.get_embeddings([query_text])[0]

    # 3. Search LanceDB
    print("Searching LanceDB...")
    results = vdb.query(query_vector, limit=2)

    # 4. Display Results
    if results.empty:
        print("No results found. Did you index the document first?")
    else:
        print(f"\nFound {len(results)} relevant chunks:\n")
        for i, (idx,row) in enumerate(results.iterrows()):
            print(f"--- Result {i+1} (Score: {row.get('_distance', 'N/A')}) ---")
            print(f"Source: {row['metadata'].get('source_url', 'Unknown')}")
            print(f"Text Snippet: {row['text'][:200]}...")
            print("-" * 30)

if __name__ == "__main__":
    # Test with a question related to your Karnataka Solar Policy file
    run_test_query("What are the main objectives of the solar policy?")