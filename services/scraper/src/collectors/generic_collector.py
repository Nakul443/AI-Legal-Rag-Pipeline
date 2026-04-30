# core engine that powers the automated pipeline
'''
1. Loads the site-specific YAML config
2. Crawling the target page using AsyncWebCrawler or httpx based on the URL and config
3. Extracting rows and PDF links
'''
import asyncio
import os
from typing import List, Dict, cast
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode, CrawlResult
from utils.config_loader import load_site_config
from bs4 import BeautifulSoup
import httpx
import json
import uuid

class GenericCollector:
    def __init__(self, site_key: str):
        self.config = load_site_config(site_key)
        self.base_url = self.config['base_url']
        self.selectors = self.config['selectors']

    async def collect_links(self) -> List[Dict]:
        """
        Crawls the page and extracts document metadata (Title, Link, Date)
        based on YAML selectors.
        """
        async with AsyncWebCrawler() as crawler:
            # We use CacheMode.BYPASS to ensure we get fresh data every time
            run_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

            print(f" Starting crawl for {self.config['site_name']}...")
            raw_result = await crawler.arun(url=self.config['start_url'], config=run_config)  # type: ignore
            result = cast(CrawlResult, raw_result)  # fix Pylance: arun() has bad type stubs

            if not result.success:
                print(f" Failed to crawl {self.config['site_name']}: {result.error_message}")
                return []

            # result.soup doesn't exist in 0.8.x — parse result.html manually
            # This is safer than raw BeautifulSoup for dynamic content
            soup = BeautifulSoup(result.html or "", "html.parser")
            documents = []

            # Find all rows defined in YAML
            rows = soup.select(self.selectors['row'])

            for row in rows:
                try:
                    # Extract fields using the config mapping
                    title_el = row.select_one(self.selectors['title'])
                    link_el = row.select_one(self.selectors['link'])
                    date_el = row.select_one(self.selectors['date'])

                    if title_el and link_el:
                        # Clean up the URL (make it absolute)
                        # link_el.get('href') can return None or a list, so we cast safely
                        href = link_el.get('href')
                        if not href:
                            continue
                        href = str(href) if not isinstance(href, str) else href
                        full_url = href if href.startswith('http') else f"{self.base_url}{href}"

                        documents.append({
                            "title": title_el.get_text(strip=True),
                            "url": full_url,
                            "date": date_el.get_text(strip=True) if date_el else "N/A",
                            "source": self.config['site_name']
                        })

                except Exception as e:
                    print(f"⚠️ Skipping a row due to error: {e}")
                    continue

            print(f" Found {len(documents)} documents on {self.config['site_name']}")
            return documents

async def save_to_raw(self, doc_data: dict):
    """Saves the metadata and PDF to data/raw for the worker to process."""
    uid = str(uuid.uuid4())
    raw_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../data/raw"))
    os.makedirs(raw_dir, exist_ok=True)

    # 1. Save JSON Metadata
    doc_data['uid'] = uid
    json_path = os.path.join(raw_dir, f"{uid}.json")
    with open(json_path, "w") as f:
        json.dump(doc_data, f)

    # 2. Download PDF
    pdf_path = os.path.join(raw_dir, f"{uid}.pdf")
    async with httpx.AsyncClient(verify=False) as client:
        try:
            resp = await client.get(doc_data['url'])
            if resp.status_code == 200:
                with open(pdf_path, "wb") as f:
                    f.write(resp.content)
                print(f" Saved: {doc_data['title']}")
        except Exception as e:
            print(f" PDF Download Failed: {e}")
