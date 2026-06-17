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
            
            # Safety check for missing selectors
            if not self.selectors or 'row' not in self.selectors:
                print(f" ⚠️ No parsing layout rules mapped inside selectors for {self.config.get('site_name')}. Skipping parsing rows step.")
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
                        
                        # --- PATCH 1: STABLE ABSOLUTE URL JOIN ENHANCEMENT ---
                        # Replaced primitive f-string matching with standard urljoin semantics.
                        # This resolves domain parsing errors (like GERC's DNS Address exception) 
                        # when a site references documents on parent branches or relative assets.
                        full_url = urljoin(start_url or self.base_url, href)

                        # --- PATCH 2: CLEAN INLINE SCISSOR STRIPPING ---
                        # Prevents global template leaks (like UPERC pulling navigation layout text).
                        # Grabs text strictly from the single matching target node without structural noise.
                        raw_title = title_el.get_text(space_join=True, strip=True)
                        if len(raw_title) > 200 or not raw_title:
                            # If selector accidentally captured giant sub-tree block layout, prioritize link anchor text
                            raw_title = link_el.get_text(strip=True) or raw_title[:100] + "..."
                            if not raw_title.strip():
                                raw_title = f"Document_{href.split('/')[-1]}"

                        documents.append({
                            "title": raw_title,
                            # [FIX] Key renamed from 'url' → 'source_url' to match what worker.py reads.
                            # Previously worker.py called scraped_data.get('source_url', 'N/A') and always
                            # got 'N/A' because collector was writing 'url'. Every stored document had
                            # source_url = 'N/A', breaking Section 4.1 provenance completely.
                            "source_url": full_url,
                            # [FIX] Key renamed from 'date' → 'date_of_order' to match what worker.py reads.
                            # Previously worker.py called scraped_data.get('date_of_order', "2024-01-01")
                            # and always got the hardcoded placeholder. Real dates were silently discarded.
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
        # worker.py reads these keys directly from the JSON. Without them, every
        # field fell back to a default or pending=True, making Section 4.2 tracking useless.
        # All values are pulled from self.config (YAML) — the YAML is the right place to
        # declare authority/state/jurisdiction per site, since the collector already owns the config.
        # ──────────────────────────────────────────────────────────────

        # authority: YAML key 'forum' (e.g., "CERC", "APTEL", "SERC_MH").
        # worker.py reads 'authority' and does Forum enum lookup — must be a valid Forum member name.
        doc_data['authority'] = self.config.get('forum', self.config.get('site_name', 'CERC')).upper()

        # state: YAML key 'state' (e.g., "CENTRAL", "MH", "GJ").
        # Central forums (CERC, APTEL, SC) should set state: "CENTRAL" in their YAML.
        doc_data['state'] = self.config.get('state', 'National')

        # jurisdiction: Human-readable string for display ("Federal" or state commission name).
        doc_data['jurisdiction'] = self.config.get('jurisdiction', 'India')

        # source_domain: Extracted from source_url for lifecycle rules and dedup routing.
        source_url = doc_data.get('source_url', '')
        doc_data['source_domain'] = urlparse(source_url).netloc if source_url else None

        # scrape_date: ISO timestamp of this exact scrape run (Section 4.1 requires it).
        doc_data['scrape_date'] = datetime.utcnow().isoformat()

        # pipeline_version: Tags which version of ingestion code produced this record.
        doc_data['pipeline_version'] = PIPELINE_VERSION

        # file_size_bytes: Set to 0 now; updated to actual size after successful PDF download below.
        doc_data['file_size_bytes'] = 0

        # Use browser-like headers to avoid being blocked during PDF download
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
                    # [FIX] Record actual file size now that download succeeded.
                    # worker.py uses this to populate the Section 4.1 file_size_bytes tag.
                    doc_data['file_size_bytes'] = len(pdf_bytes)
                    print(f" Saved: {doc_data['title']} ({len(pdf_bytes)} bytes)")
                else:
                    # [FIX] Trap hidden non-200 connection drops (e.g. 403 Forbidden blocks)
                    print(f" ❌ Server Rejected Download Request: HTTP {resp.status_code} for URL: {source_url}")
            except Exception as e:
                print(f" PDF Download Failed: {e}")

        # Write JSON after PDF attempt so file_size_bytes reflects real outcome.
        # If download failed, file_size_bytes=0 signals worker.py that PDF is missing.
        with open(os.path.join(raw_dir, f"{uid}.json"), "w") as f:
            json.dump(doc_data, f)