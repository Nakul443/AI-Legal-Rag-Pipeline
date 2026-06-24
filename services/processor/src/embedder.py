# Embedder
# This file is responsible for taking text chunks and converting them into numerical vectors.

import os
from openai import OpenAI, OpenAIError
from dotenv import load_dotenv

load_dotenv()

class Embedder:
    def __init__(self):
        # Initialize the OpenAI client once. The client uses an internal 
        # connection pool that persists across multiple requests.
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in .env file.")
            
        self.client = OpenAI(api_key=api_key)
        self.model = "text-embedding-3-small"

    def get_embeddings(self, text_list: list[str], batch_size: int = 100):
        """
        Converts text chunks into vectors. 
        [PERFORMANCE] Now supports internal batching to keep API requests stable.
        """
        all_embeddings = []
        
        # Process in smaller chunks to avoid request timeout on large documents
        for i in range(0, len(text_list), batch_size):
            batch = [t.replace("\n", " ").strip() for t in text_list[i:i + batch_size]]
            
            try:
                response = self.client.embeddings.create(
                    input=batch,
                    model=self.model
                )
                all_embeddings.extend([data.embedding for data in response.data])
            except OpenAIError as e:
                print(f"Error generating embeddings from OpenAI: {e}")
                raise
                
        return all_embeddings