# "control center"
# This file will be the main entry point for the scraper service. It will receive a URL from the API, send it to Jina, and return the structured Markdown back to the API.
# ties the schema and the Jina Client together to fetch a document and save it locally for testing before scaling to 100GB data.

import os
import json
import uuid
from schema import LegalDocument
from jina_client import JinaClient

def test_scrape(url: str, jurisdiction: str, category: str):
    client = JinaClient()
    
    print(f"Scraping: {url}...")
    markdown_content = client.fetch_markdown(url)
    
    # Create the structured document
    doc = LegalDocument(
        uid=str(uuid.uuid4()),
        title="Sample Legal Document", # We will automate title extraction later
        source_url=url,
        jurisdiction=jurisdiction,
        category=category,
        document_type="Regulation",
        content_markdown=markdown_content
    )
    
    # Save locally to data/raw for verification
    file_path = f"data/raw/{doc.uid}.json"
    with open(file_path, "w") as f:
        f.write(doc.json())
    
    print(f"Success! Saved to {file_path}")

if __name__ == "__main__":
    # Test with a single CERC or Electricity related URL
    sample_url = "https://cercind.gov.in/" 
    test_scrape(sample_url, "Federal", "Electricity")