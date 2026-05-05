# core engine that powers the automated pipeline
'''
1. Loads the site-specific YAML config
2. Crawling the target page using AsyncWebCrawler or httpx based on the URL and config
3. Extracting rows and PDF links
'''

# main.py calls this file for each site, which then uses the config to determine
# how to crawl and extract data.

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
        self.base_url = self.config['base_url'].rstrip('/')
        self.selectors = self.config.get('selectors', {})

    async def collect_links(self) -> List[Dict]:
        """
        Crawls the page and extracts document metadata. 
        Bypasses browser for direct PDF links.
        """
        # NEW: Direct PDF Bypass for sites like TNERC
        if self.config['start_url'].lower().endswith('.pdf'):
            print(f" ℹ️ Direct PDF detected for {self.config['site_name']}. Bypassing browser...")
            return [{
                "title": self.config.get('site_name', 'Direct Download'),
                "url": self.config['start_url'],
                "date": "N/A",
                "source": self.config['site_name']
            }]

        async with AsyncWebCrawler() as crawler:
            wait_selector = self.config.get('wait_for', 'body')
            
            run_config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                # Using 'body' as a fallback, but SECI needs its dataTable
                wait_for=f"css:{wait_selector}",
                js_code="await new Promise(r => setTimeout(r, 2000));" 
            )

            print(f" Starting crawl for {self.config['site_name']}...")
            try:
                raw_result = await crawler.arun(url=self.config['start_url'], config=run_config)
                result = cast(CrawlResult, raw_result)
            except Exception as e:
                print(f" ❌ Crawler crashed for {self.config['site_name']}: {e}")
                return []

            if not result.success:
                print(f" Failed to crawl {self.config['site_name']}: {result.error_message}")
                return []

            soup = BeautifulSoup(result.html or "", "html.parser")
            documents = []
            
            # Safety check for missing selectors
            if not self.selectors or 'row' not in self.selectors:
                return []

            rows = soup.select(self.selectors['row'])

            for row in rows:
                try:
                    title_el = row.select_one(self.selectors['title']) if self.selectors.get('title') else None
                    link_el = row.select_one(self.selectors['link']) if self.selectors.get('link') else None
                    date_el = row.select_one(self.selectors['date']) if self.selectors.get('date') else None

                    if title_el and link_el:
                        href = link_el.get('href')
                        if not href: continue
                        
                        href = str(href).strip()
                        full_url = href if href.startswith('http') else f"{self.base_url}/{href.lstrip('/')}"

                        documents.append({
                            "title": title_el.get_text(strip=True),
                            "url": full_url,
                            "date": date_el.get_text(strip=True) if date_el else "N/A",
                            "source": self.config['site_name']
                        })
                except Exception as e:
                    print(f"⚠️ Skipping a row: {e}")
                    continue

            print(f" Found {len(documents)} documents on {self.config['site_name']}")
            return documents

    async def save_to_raw(self, doc_data: dict):
        """Saves metadata and PDF with httpx."""
        uid = str(uuid.uuid4())
        raw_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../data/raw"))
        os.makedirs(raw_dir, exist_ok=True)

        doc_data['uid'] = uid
        with open(os.path.join(raw_dir, f"{uid}.json"), "w") as f:
            json.dump(doc_data, f)

        # Use browser-like headers to avoid being blocked during PDF download
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with httpx.AsyncClient(verify=False, headers=headers) as client:
            try:
                resp = await client.get(doc_data['url'], follow_redirects=True)
                if resp.status_code == 200:
                    with open(os.path.join(raw_dir, f"{uid}.pdf"), "wb") as f:
                        f.write(resp.content)
                    print(f" ✅ Saved: {doc_data['title']}")
            except Exception as e:
                print(f" ❌ PDF Download Failed: {e}")