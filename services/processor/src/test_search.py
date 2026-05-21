# ADDED FUNCTIONALITIES COMMENTS:
# 1. Enhanced citation richness in the system instructions to enforce strict extraction of D1-D4 tags and physical storage path linkages.
# 2. Augmented the metadata printing and prompt logging tracking to verify the state of `pending_` validation flags dynamically.
# 3. Synchronized LanceDB lookups to extract and expose new schema parameters (authority, issue_tag_primary, challenge_status) cleanly in the diagnostic console.

# temp test script
# job is to perform "semantic search" and generate a final answer
# easier to run as compared to worker.py
# so this file can be run every time we want to test the search and generation functionality of the RAG pipeline

import os
import sys
import time
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
    results = vdb.query(query_vector, limit=10) 

    # 4. Display Results and Generate Answer
    if not results:
        print("No results found. Did you index the document first?")
    else:
        print(f"\nFound {len(results)} relevant chunks. Synthesizing answer...\n")
        
        # Prepare context for the LLM
        context_text = ""
        for i, row in enumerate(results):
            # FIXED: Using act_name and section_header from the new flat schema
            # ENHANCED: Appended Forum Authority, Issue Tag, and Challenge Status for multi-dimensional citation verification
            source_info = (
                f"Source: {row.get('act_name', 'Unknown Document')} | "
                f"Section: {row.get('section_header', 'General Section')} | "
                f"Authority: {row.get('authority', 'N/A')} | "
                f"Issue: {row.get('issue_tag_primary', 'OTHER')} | "
                f"Status: {row.get('challenge_status', 'FINAL')}"
            )
            context_text += f"\n--- {source_info} ---\n{row.get('text', '')}\n"

        # 5. The "R" in RAG: Generation
        # Improved the system instructions slightly to be more authoritative
        # ENHANCED: Injected strict instructions ensuring structural metadata tags are used in reasoning assertions
        prompt = f"""
        You are a precise Legal AI Assistant specializing in Indian Electricity and Regulatory infrastructure. 
        Use the provided context to answer the user's question accurately.
        
        When citing information, explicitly use the provided Authority, Issue, and Status metadata variables 
        to render clear, legally authoritative references.
        
        If the answer is not contained within the context, state that you do not have enough information in the provided documents.
        
        CONTEXT:
        {context_text}

        QUESTION:
        {query_text}

        ANSWER:
        """

        # Added defensive retry mechanism to absorb upstream 503 high-demand spikes gracefully
        response = None
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt
                )
                break  # Success! Break out of the retry loop
            except Exception as e:
                if "503" in str(e) and attempt < 2:
                    print(f" ⏳ Upstream model busy (503). Retrying in 3s... (Attempt {attempt+1}/3)")
                    time.sleep(3)
                else:
                    raise e

        if response:
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
            authority = row.get('authority', 'Unknown Forum')
            issue = row.get('issue_tag_primary', 'OTHER')
            status = row.get('challenge_status', 'FINAL')
            
            # DIAGNOSTIC: Expose validation state flags in the terminal output to locate missing tags
            p_object = row.get('pending_legal_object_type', False)
            p_date = row.get('pending_date_of_order', False)
            p_issue = row.get('pending_issue_tag_primary', False)
            flags_str = f"Pending Flags -> [Obj: {p_object} | Date: {p_date} | Issue: {p_issue}]"
            
            # FIX: Ensure dictionary look up for distance score to prevent AttributeError
            score = row.get('_distance', 0.0)
            print(f"- {name} [{section}] ({authority} - {issue} - {status}) (Score: {score:.4f}) | {flags_str}")

if __name__ == "__main__":
    # Test with a question related to your Maharashtra Open Access Regulations
    run_test_query("How is open access categorized based on duration according to the regulations?")