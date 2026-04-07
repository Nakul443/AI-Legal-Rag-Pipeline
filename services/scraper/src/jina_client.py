# the "bridge" between internet and the pipeline
# Instead of writing messy scraping code for every website, this file will send a URL to Jina and get back clean, structured Markdown.

import os
import requests
from dotenv import load_dotenv

load_dotenv()

class JinaClient:
    def __init__(self):
        self.api_key = os.getenv("JINA_API_KEY")
        self.base_url = "https://r.jina.ai/"

    def fetch_markdown(self, url: str) -> str:
        """Converts any URL to clean Markdown using Jina Reader."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Return-Format": "markdown"
        }
        
        response = requests.get(f"{self.base_url}{url}", headers=headers)
        response.raise_for_status()
        return response.text