# "control center"
# This file will be the main entry point for the scraper service. It will receive a URL from the API, send it to Crawl4AI, and return the structured Markdown back to the API.
# ties the schema and the Crawl4AI Client together to fetch a document and save it locally for testing before scaling to 100GB data.

import json
import os
import uuid
import asyncio  # Added for async support
from schema import LegalDocument
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode, CrawlResult

async def test_scrape(url: str, jurisdiction: str, category: str):
    # using crawl4AI's AsyncWebCrawler
    # This allows for local browser-based scraping and better PDF discovery
    
    browser_config = BrowserConfig(headless=True)
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        print(f"Scraping: {url}...")
        
        # Execute the crawl
        result = await crawler.arun(url=url, config=run_config)
        
        # VS Code Fix: Narrow the type so Pylance knows it's not a Generator
        if not isinstance(result, CrawlResult):
            return

        if not result.success:
            print(f"Failed: {result.error_message}")
            return

        # Accessing nested markdown object safely
        markdown_content = result.markdown.raw_markdown if result.markdown else ""
        
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
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(doc.json())
        
        print(f"Success! Saved to {file_path}")

if __name__ == "__main__":
    # Test with a single CERC or Electricity related URL
    sample_url = "https://cercind.gov.in/recent_orders.html" 
    # Use asyncio to run the async test_scrape function
    asyncio.run(test_scrape(sample_url, "Federal", "Electricity"))