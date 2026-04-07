# legal assistant API
# takes raw text snippets from LanceDB and feeds them into the LLM
# "translator," turns database rows into professional, human-readable answers to user questions.

import os
from google import generativeai as genai
from dotenv import load_dotenv

load_dotenv()

class LegalAssistant:
    def __init__(self):
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        # We use Flash-Lite/Flash for speed and cost-efficiency on 100GB of context
        self.model = genai.GenerativeModel('gemini-2.5-flash')

    def ask_legal_question(self, question: str, context_chunks: list):
        """Combines the user's question with retrieved legal snippets."""
        
        # Combine all the chunks into one big string of "Context"
        context_text = "\n\n".join([f"Source: {c}" for c in context_chunks])

        prompt = f"""
        You are a highly skilled Indian Regulatory & Legal Expert. 
        Use the provided context from official documents to answer the user's question.
        
        Rules:
        1. If the answer isn't in the context, say you don't know. Do not hallucinate.
        2. Cite the source URL or Title if available in the context.
        3. Keep the tone professional and precise.

        Context:
        {context_text}

        User Question: {question}
        """

        response = self.model.generate_content(prompt)
        return response.text