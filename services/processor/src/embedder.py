# Embedder
# puts data into vector database
# This file will be responsible for taking the structured Markdown documents, chunking them, generating embeddings
# file takes your text chunks and converts them into long lists of numbers (vectors).
# we compare the "numbers" of their question to the "numbers" of your 100GB of data to find the best match

import os
# from openai import OpenAI
from dotenv import load_dotenv
# Switched to the new 2026 SDK to remove the FutureWarning
from google import genai 
from google.genai import types

load_dotenv()

# for local testing
class Embedder:
    def __init__(self):
        # Configure the API key for Google Generative AI
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in .env file. Please add it to generate embeddings.")
            
        # Using the new Client architecture for 2026
        self.client = genai.Client(api_key=api_key)
        # THIS IS THE ACTUAL STABLE MODEL NAME FOR 2026
        self.model_name = "gemini-embedding-001"

    def get_embeddings(self, text_list: list[str]):
        """Generates vectors using the Google GenAI SDK."""
        # Use embed_content with the corrected model name and task type
        # The task_type "retrieval_document" optimizes the vectors for being searched
        # Updated to the new SDK syntax: self.client.models.embed_content
        result = self.client.models.embed_content(
            model=self.model_name,
            contents=[types.Content(parts=[types.Part(text=text)]) for text in text_list],
            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT")
        )
        
        # In the new SDK, response.embeddings is a list of objects; we extract the 'values'
        if result and hasattr(result, 'embeddings') and result.embeddings:
            return [e.values for e in result.embeddings]
        else:
            raise ValueError(f"Failed to generate embeddings. Response: {result}")


# # embed data into vector database, uses OpenAI's embedding model to convert text into vectors for efficient retrieval.
# class Embedder:
#     def __init__(self):
#         self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
#         self.model = "text-embedding-3-small"

#     def get_embeddings(self, text_list: list[str]):
#         """Converts a batch of text chunks into vectors."""
#         # Extract just the vector data from the response
#         return [data.embedding for data in response.data]