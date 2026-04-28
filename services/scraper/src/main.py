"""
# "control center"
# This file will be the main entry point for the scraper service. It will receive a URL from the API, 
# send it to Crawl4AI (for JS-heavy sites) OR use a lightweight fetcher (for simple PDF discovery),
# and return the structured Markdown back to the API.
# ties the schema and the Crawl4AI Client together to fetch a document and save it locally for testing before scaling to 100GB data.

# looks at a website and decides whether to use
# a simple, fast script or heavy-duty virtual browser
"""

import os
import sys

# absolute path to project root
# We calculate this first to ensure local imports work regardless of execution context
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))

# add project root to sys.path for imports
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import uuid
from bs4 import BeautifulSoup
import asyncio
import json
import httpx
# These imports now work because of the sys.path.insert above
from schema import LegalDocument
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode, CrawlResult
from mnre_crawler import MNRECrawler

# --- LIGHTWEIGHT HELPERS ---
# Use these for simple sites like India Code to save local resources
def fetch_lightweight(url: str):
    """Fetches page content without a browser using httpx."""
    headers = {"User-Agent": "Mozilla/5.0"}
    with httpx.Client(headers=headers, follow_redirects=True, timeout=10.0) as client:
        res = client.get(url)
        return res.text

# decision engine
# checks URL and decides whether to use this or not
def should_use_browser(url: str) -> bool:
    """
    AUTO-SELECTOR LOGIC:
    Decides if we need the heavy Crawl4AI browser or just lightweight HTTPX.
    """
    # 1. Simple gov portals or direct PDF links don't need a browser
    lightweight_domains = ["indiacode.nic.in", "ceew.in", "caselaw.in"]
    if any(domain in url.lower() for domain in lightweight_domains):
        return False
    
    # 2. Sites known for heavy JavaScript or dynamic content (CERC, SCC, Indian Kanoon)
    # CERC often uses ASP.NET which can be tricky without a browser
    browser_heavy_domains = ["cercind.gov.in", "indiankanoon.org", "sci.gov.in", "mnre.gov.in"]
    if any(domain in url.lower() for domain in browser_heavy_domains):
        return True
        
    # Default: Use browser if unsure to ensure we don't miss content
    return True

async def test_scrape(url: str, jurisdiction: str, category: str, force_browser: bool | None = None):
    # The system now automatically decides which service to use based on the URL.
    # This saves local computation while ensuring high-quality extraction.

    markdown_content = ""
    # Dynamic logic: found_title is now set per document discovered
    
    # Determine which engine to use
    use_browser = force_browser if force_browser is not None else should_use_browser(url)

    raw_html = ""

    if use_browser:
        print(f" Auto-Selected: Crawl4AI (Browser) for {url}")
        browser_config = BrowserConfig(headless=True)
        run_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=url, config=run_config)
            
            # --- ADD THIS TYPE GUARD ---
            if not isinstance(result, CrawlResult):
                print("Result is not a valid CrawlResult object.")
                return
            # ---------------------------

            if not result.success:
                # Now Pylance knows result has error_message!
                print(f"Failed Crawl4AI: {result.error_message}")
                return
            
            raw_html = result.html
            markdown_content = result.markdown.raw_markdown if result.markdown else ""
    else:
        print(f" Auto-Selected: Lightweight Fetcher for {url}")
        try:
            raw_html = fetch_lightweight(url)
            soup = BeautifulSoup(raw_html, 'html.parser')
            # Basic cleanup: remove script/style tags
            for script in soup(["script", "style"]):
                script.decompose()
            markdown_content = soup.get_text(separator='\n')

        # Specific catch for the fallback mechanism
        # just in case the lightweight fetcher fails
        except (httpx.HTTPError, ConnectionError) as e:
            print(f"Lightweight failed, falling back to browser... Reason: {e}")
            return await test_scrape(url, jurisdiction, category, force_browser=True)
            
        # Catching specific File I/O issues during save
        except IOError as e:
            print(f"Could not save file to disk: {e}")
            return

    # --- DYNAMIC MNRE DISCOVERY LOGIC ---
    if "mnre.gov.in" in url:
        print(f" Processing MNRE Portal: Finding latest documents...")
        crawler = MNRECrawler()
        discovered_docs = crawler.parse_document_table(raw_html)
        
        # We only process the top 3 newest to save quota and test logic
        for item in discovered_docs[:3]:
            doc_uid = str(uuid.uuid4())
            print(f" -> Found: {item['title']} ({item['date'].strftime('%Y-%m-%d')})")
            
            # Create the structured document using dynamic data
            doc = LegalDocument(
                uid=doc_uid,
                title=item['title'], 
                source_url=item['link'],
                jurisdiction=jurisdiction,
                category=category,
                document_type="Policy/Guideline",
                content_markdown=f"Date: {item['date']}\n\nDownload Link: {item['link']}\n\nSummary placeholder for discovery."
            )
            save_doc_locally(doc)
    else:
        # Fallback for non-MNRE sites using standard single-page logic
        doc = LegalDocument(
            uid=str(uuid.uuid4()),
            title="Standard Scrape Result", 
            source_url=url,
            jurisdiction=jurisdiction,
            category=category,
            document_type="Regulation",
            content_markdown=markdown_content
        )
        save_doc_locally(doc)

def save_doc_locally(doc: LegalDocument):
    """Helper to save the structured document to data/raw."""
    # Ensure save_dir exists relative to project root
    save_dir = os.path.join(project_root, "data", "raw")
    os.makedirs(save_dir, exist_ok=True)
    
    file_path = os.path.join(save_dir, f"{doc.uid}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(doc.json())
    print(f" Success! Saved: {file_path}")

if __name__ == "__main__":
    # Test 1: MNRE Solar Policy (Dynamic Discovery)
    mnre_solar_url = "https://mnre.gov.in/en/solar-policies-and-guidelines/"
    
    # Test 2: India Code (Lightweight)
    # india_code_url = "https://www.indiacode.nic.in/handle/123456789/1362"
    
    # Test 3: CERC (Browser)
    # cerc_url = "https://cercind.gov.in/recent_orders.html"
    
    asyncio.run(test_scrape(mnre_solar_url, "Federal", "Solar"))