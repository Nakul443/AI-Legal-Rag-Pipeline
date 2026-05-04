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
from typing import cast

# absolute path to project root
# We calculate this first to ensure local imports work regardless of execution context
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
src_dir = os.path.abspath(os.path.dirname(__file__))  # services/scraper/src/

if project_root not in sys.path:
    sys.path.insert(0, project_root)
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

import uuid
from bs4 import BeautifulSoup
import asyncio
import httpx
import json

from models.schema import LegalDocument
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode, CrawlResult
from collectors.generic_collector import GenericCollector # Updated: Using the generic engine

# --- LIGHTWEIGHT HELPERS ---
# Use these for simple sites like India Code to save local resources
def fetch_lightweight(url: str) -> str:
    """Fetches page content without a browser using httpx."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    with httpx.Client(headers=headers, follow_redirects=True, timeout=15.0, verify=False) as client:
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
    lightweight_domains = ["indiacode.nic.in", "ceew.in", "caselaw.in", "exam.tnebnet.org"]
    if any(domain in url.lower() for domain in lightweight_domains):
        return False

    # 2. Sites known for heavy JavaScript or dynamic content (CERC, SCC, Indian Kanoon)
    # CERC often uses ASP.NET which can be tricky without a browser
    browser_heavy_domains = ["cercind.gov.in", "indiankanoon.org", "sci.gov.in", "mnre.gov.in", "mahadiscom.in", "gercin.org", "seci.co.in"]
    if any(domain in url.lower() for domain in browser_heavy_domains):
        return True

    # Default: Use browser if unsure to ensure we don't miss content
    return True


# helper function to handle file download
async def download_pdf(url: str, save_path: str):
    """Downloads a PDF from a URL to a local path."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    async with httpx.AsyncClient(headers=headers, follow_redirects=True, verify=False) as client:
        try:
            response = await client.get(url, timeout=30.0)
            if response.status_code == 200:
                with open(save_path, "wb") as f:
                    f.write(response.content)
                return True
        except Exception as e:
            print(f" Failed to download PDF from {url}: {e}")
    return False


async def test_scrape(site_key: str, force_browser: bool | None = None) -> None:
    # The system now uses the GenericCollector to load configuration-based selectors.
    # This enables scaling to 100+ sites by simply adding a YAML config.
    
    collector = GenericCollector(site_key)
    url = collector.config['start_url']
    jurisdiction = collector.config['jurisdiction']
    category = collector.config['category']
    
    # Determine which engine to use
    use_browser = force_browser if force_browser is not None else should_use_browser(url)
    
    print(f" Processing {collector.config['site_name']} Portal: Finding latest documents...")
    
    # --- ENHANCED BROWSER CONFIG FOR ANTI-BOT ---
    # Updated: Using try-except for BrowserConfig to handle Crawl4AI version variances
    try:
        browser_config = BrowserConfig(
            headless=True,
            extra_args=["--disable-blink-features=AutomationControlled"], # Standard stealth
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )
    except TypeError:
        # Fallback for older or strictly limited versions
        browser_config = BrowserConfig(headless=True)
    
    # Use our generic collector to find links based on YAML selectors
    # Note: If use_browser is True, the collector uses Crawl4AI inside.
    discovered_docs = await collector.collect_links()
    
    save_dir = os.path.join(project_root, "data", "raw")
    os.makedirs(save_dir, exist_ok=True)

    # Process first 3 discovered items to test the pipeline
    for item in discovered_docs[:1]:
        doc_uid = str(uuid.uuid4())
        pdf_filename = f"{doc_uid}.pdf"
        pdf_path = os.path.join(save_dir, pdf_filename)
        
        print(f" -> Downloading: {item['title']}...")
        success = await download_pdf(item['url'], pdf_path)
        
        if success:
            # Create the structured document with the actual local path
            doc = LegalDocument(
                uid=doc_uid,
                title=item['title'], 
                source_url=item['url'],
                jurisdiction=jurisdiction,
                category=category,
                document_type="Policy/Guideline",
                content_markdown=f"LOCAL_PDF_PATH: {pdf_path}" # Signals processor to parse this PDF
            )
            save_doc_locally(doc)

def save_doc_locally(doc: LegalDocument) -> None:
    """Helper to save the structured document to data/raw."""
    save_dir = os.path.join(project_root, "data", "raw")
    os.makedirs(save_dir, exist_ok=True)

    file_path = os.path.join(save_dir, f"{doc.uid}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(doc.model_dump_json())
    print(f" Success! Saved: {file_path}")

if __name__ == "__main__":
    # 1. Define the path to your configs folder
    config_dir = os.path.join(project_root, "services/scraper/configs")
    
    # 2. Get all .yaml files (mnre, cerc, cea, seci)
    # This automatically builds your "array" from the files you've created
    sites_to_scrape = [
        f.replace(".yaml", "") 
        for f in os.listdir(config_dir) 
        if f.endswith(".yaml")
    ]

    async def run_all_scrapers(sites):
        print(f" Starting batch scrape for: {', '.join(sites)}")
        for site in sites:
            try:
                # We await each one so they run sequentially, 
                # preventing your CPU from exploding with 4 browsers at once.
                await test_scrape(site)
            except Exception as e:
                print(f" Failed to scrape {site}: {str(e)}")
                continue # Move to the next site if one fails
        print(" All sites processed. Check data/raw for results.")

    # 3. Execute the full loop
    asyncio.run(run_all_scrapers(sites_to_scrape))