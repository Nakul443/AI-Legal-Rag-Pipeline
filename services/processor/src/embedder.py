# Embedder
# puts data into vector database
# This file will be responsible for taking the structured Markdown documents, chunking them, generating embeddings
# file takes your text chunks and converts them into long lists of numbers (vectors).
# we compare the "numbers" of their question to the "numbers" of your 100GB of data to find the best match

import os
# from openai import OpenAI
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from google import generativeai as genai # for local testing with Gemini's free embedding model

load_dotenv()

# for local testing
class Embedder:
    def __init__(self):
        # Configure the API key for Google Generative AI
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        # THIS IS THE ACTUAL STABLE MODEL NAME FOR 2026
        self.model_name = "models/gemini-embedding-001"

    def get_embeddings(self, text_list: list[str]):
        """Generates vectors using the Google GenAI SDK."""
        # Use embed_content with the corrected model name and task type
        result = genai.embed_content(
            model=self.model_name,
            content=text_list,
            task_type="retrieval_document" # CRITICAL: This is required for gemini-embedding-001
        )
        
        # In the generativeai library, the result is a dictionary with an 'embedding' key
        return result['embedding']


# # embed data into vector database, uses OpenAI's embedding model to convert text into vectors for efficient retrieval.
# class Embedder:
#     def __init__(self):
#         self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
#         self.model = "text-embedding-3-small"

#     def get_embeddings(self, text_list: list[str]):
#         """Converts a batch of text chunks into vectors."""
#         response = self.client.embeddings.create(
#             input=text_list,
#             model=self.model
#         )
#         # Extract just the vector data from the response
#         return [data.embedding for data in response.data]