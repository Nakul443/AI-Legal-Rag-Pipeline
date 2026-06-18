# services/scraper/src/collectors/generic_collector.py
# core engine that powers the automated pipeline
'''
1. Loads the site-specific YAML config
2. Crawling the target page using AsyncWebCrawler or httpx based on the URL and config
3. Extracting rows and PDF links
'''
# main.py calls this file for each site, which then uses the config to determine
# how to crawl and extract data.

# [FIX] ADDED FUNCTIONALITIES COMMENTS:
# 1. Renamed 'url' key to 'source_url' in save_to_raw() output JSON — worker.py reads 'source_url'
#    and was silently getting 'N/A' for every document (breaking Section 4.1 Rule 02 provenance).
# 2. Renamed 'date' key to 'date_of_order' — worker.py reads 'date_of_order' and was silently
#    falling back to hardcoded "2024-01-01" for every document.
# 3. Added scrape-time fields to save_to_raw() JSON that Section 4.1 requires populated at scrape time:
#    authority, state, jurisdiction, source_domain, scrape_date, pipeline_version, file_size_bytes.
#    All sourced from YAML config so no guessing happens downstream in worker.py.
# 4. Added pending_source_url flag logic: if PDF download fails, source_url stays as the scraped href
#    but we still record it — the file_size_bytes=0 signals the download failed for worker.py.

import asyncio
import os
from typing import List, Dict, cast, Any
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode, CrawlResult
from utils.config_loader import load_site_config
from bs4 import BeautifulSoup
import httpx
import json
import uuid
from datetime import datetime
from urllib.parse import urlparse, urljoin

# Pipeline version tag — bump this when ingestion logic changes so
# every document carries the version of code that produced it (Section 4.1)
PIPELINE_VERSION = "1.0"

class GenericCollector:
    def __init__(self, site_key: str):
        self.config = load_site_config(site_key)
        # Handle structural fallback parameters if config values are completely empty or unassigned
        if not self.config:
            self.config = {}
        
        # Pull baseline operational elements safely
        base_url_raw = self.config.get('base_url', f"https://{site_key}.gov.in")
        self.base_url = str(base_url_raw).rstrip('/')
        
        # --- FIX: FALLBACK UNINITIALIZED SELECTORS ---
        # Ensures that even if a site config completely omits the selectors map block, 
        # it registers a valid empty dictionary rather than raising an AttributeError.
        self.selectors = self.config.get('selectors', {})
        if self.selectors is None:
            self.selectors = {}

    async def collect_links(self, run_config: Any = None) -> List[Dict]:
        """
        Crawls the page and extracts document metadata. 
        Bypasses browser for direct PDF links.
        """
        start_url = self.config.get('start_url', '')
        
        # NEW: Direct PDF Bypass for sites like TNERC
        if start_url and str(start_url).lower().endswith('.pdf'):
            print(f" ℹ️ Direct PDF detected for {self.config.get('site_name', self.base_url)}. Bypassing browser...")
            return [{
                "title": self.config.get('site_name', 'Direct Download'),
                # [FIX] Use 'source_url' so worker.py can read it directly without falling back to 'N/A'
                "source_url": start_url,
                "date_of_order": "N/A",
                "source": self.config.get('site_name', 'Direct Download')
            }]

        async with AsyncWebCrawler() as crawler:
            wait_selector = self.config.get('wait_for', 'body')
            
            # Use runtime configuration matrix passed from main control center, or fall back to default
            if run_config is None:
                run_config = CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS,
                    # Using 'body' as a fallback, but SECI needs its dataTable
                    wait_for=f"css:{wait_selector}",
                    js_code="await new Promise(r => setTimeout(r, 2000));" 
                )
            print(f" Starting crawl for {self.config.get('site_name', 'Unknown Site')}...")
            try:
                raw_result = await crawler.arun(url=start_url or self.base_url, config=run_config)
                result = cast(CrawlResult, raw_result)
            except Exception as e:
                print(f" ❌ Crawler crashed for {self.config.get('site_name', 'Unknown Site')}: {e}")
                return []

            if not result.success:
                print(f" Failed to crawl {self.config.get('site_name', 'Unknown Site')}: {result.error_message}")
                return []

            soup = BeautifulSoup(result.html or "", "html.parser")
            documents = []
            
            # ──────────────────────────────────────────────────────────────
            # NEW FALLBACK AUTO-DISCOVERY STRATEGY
            # If explicit parsing rules aren't defined or miss, fallback to target 
            # scanning the entire document DOM layout for explicit PDF download extensions.
            # ──────────────────────────────────────────────────────────────
            has_valid_selectors = self.selectors and 'row' in self.selectors
            rows = soup.select(self.selectors['row']) if has_valid_selectors else []

            if not rows:
                print(f" ⚠️ Targeted row selectors returned zero items. Executing fallback anchor matching logic...")
                # Search all hyperlinks on the page containing explicit structural file targets
                for link_tag in soup.find_all('a', href=True):
                    href_str = link_tag.get('href', '').strip()
                    if '.pdf' in href_str.lower():
                        full_url = urljoin(start_url or self.base_url, href_str)
                        anchor_text = link_tag.get_text(strip=True) or f"Document_{href_str.split('/')[-1]}"
                        
                        # Avoid duplicates
                        if not any(d['source_url'] == full_url for d in documents):
                            documents.append({
                                "title": anchor_text[:120],
                                "source_url": full_url,
                                "date_of_order": "N/A",
                                "source": self.config.get('site_name', 'Generic')
                            })
            else:
                # Execute original patterned mapping logic
                for row in rows:
                    try:
                        title_el = row.select_one(self.selectors['title']) if self.selectors.get('title') else None
                        link_el = row.select_one(self.selectors['link']) if self.selectors.get('link') else None
                        date_el = row.select_one(self.selectors['date']) if self.selectors.get('date') else None

                        if title_el and link_el:
                            href = link_el.get('href')
                            if not href: continue
                            
                            href = str(href).strip()
                            
                            # --- PATCH 1: STABLE ABSOLUTE URL JOIN ENHANCEMENT ---
                            full_url = urljoin(start_url or self.base_url, href)

                            # --- PATCH 2: CLEAN INLINE SCISSOR STRIPPING ---
                            raw_title = title_el.get_text(separator=" ", strip=True)
                            if len(raw_title) > 200 or not raw_title:
                                raw_title = link_el.get_text(strip=True) or raw_title[:100] + "..."
                                if not raw_title.strip():
                                    raw_title = f"Document_{href.split('/')[-1]}"

                            documents.append({
                                "title": raw_title,
                                "source_url": full_url,
                                "date_of_order": date_el.get_text(strip=True) if date_el else "N/A",
                                "source": self.config.get('site_name', 'Generic')
                            })
                    except Exception as e:
                        print(f"⚠️ Skipping a row: {e}")
                        continue

            print(f" Found {len(documents)} documents on {self.config.get('site_name', 'Unknown Site')}")
            return documents

    async def save_to_raw(self, doc_data: dict):
        """Saves metadata and PDF with httpx."""
        uid = str(uuid.uuid4())
        raw_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../data/raw"))
        os.makedirs(raw_dir, exist_ok=True)

        doc_data['uid'] = uid

        # ──────────────────────────────────────────────────────────────
        # [FIX] Section 4.1: Populate all scrape-time fields here before writing the JSON.
        # Fallback variants normalized to ensure 'VALID_STATES' compliance downstream.
        # ──────────────────────────────────────────────────────────────
        raw_forum = self.config.get('forum') or self.config.get('site_name') or 'CERC'
        doc_data['authority'] = str(raw_forum).upper()
        
        raw_state = self.config.get('state') or 'CENTRAL'
        if str(raw_state).upper() in ['NATIONAL', 'INDIA', 'N/A', '']:
            raw_state = 'CENTRAL'
        doc_data['state'] = str(raw_state).upper()
        
        doc_data['jurisdiction'] = self.config.get('jurisdiction', 'India')

        source_url = doc_data.get('source_url', '')
        doc_data['source_domain'] = urlparse(source_url).netloc if source_url else None
        doc_data['scrape_date'] = datetime.utcnow().isoformat()
        doc_data['pipeline_version'] = PIPELINE_VERSION
        doc_data['file_size_bytes'] = 0

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/pdf,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": self.base_url
        }
        
        async with httpx.AsyncClient(verify=False, headers=headers, timeout=30.0) as client:
            try:
                if not source_url or not source_url.startswith('http'):
                    raise ValueError(f"Malformed or missing target download tracking link: '{source_url}'")
                    
                resp = await client.get(source_url, follow_redirects=True)
                
                if resp.status_code == 200:
                    pdf_bytes = resp.content
                    with open(os.path.join(raw_dir, f"{uid}.pdf"), "wb") as f:
                        f.write(pdf_bytes)
                    doc_data['file_size_bytes'] = len(pdf_bytes)
                    print(f" Saved: {doc_data['title']} ({len(pdf_bytes)} bytes)")
                else:
                    print(f" Server Rejected Download Request: HTTP {resp.status_code} for URL: {source_url}")
            except Exception as e:
                print(f" PDF Download Failed: {e}")

        with open(os.path.join(raw_dir, f"{uid}.json"), "w") as f:
            json.dump(doc_data, f)