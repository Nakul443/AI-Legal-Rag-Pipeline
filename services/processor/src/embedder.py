# Embedder
# puts data into vector database
# This file is responsible for taking text chunks and converting them into numerical vectors.

import os
from openai import OpenAI, OpenAIError
from dotenv import load_dotenv

load_dotenv()

class Embedder:
    def __init__(self):
        # Initialize the OpenAI client using the key from your .env file
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in .env file. Please add it to generate embeddings.")
            
        self.client = OpenAI(api_key=api_key)
        # Using the most cost-effective and high-performance model
        self.model = "text-embedding-3-small"

    def get_embeddings(self, text_list: list[str]):
        """Converts a batch of text chunks into vectors using OpenAI."""
        # OpenAI recommends stripping newlines for better performance
        cleaned_texts = [text.replace("\n", " ").strip() for text in text_list]
        
        try:
            response = self.client.embeddings.create(
                input=cleaned_texts,
                model=self.model
            )
            
            # Extract the vector values from the response
            return [data.embedding for data in response.data]
            
        except OpenAIError as e:
            # Handle potential API errors (e.g., rate limits, connectivity)
            print(f"Error generating embeddings from OpenAI: {e}")
            raise