# crawler to extract title, issue date, download link
# using beautifulsoup to parse HTML

import re
from datetime import datetime
from bs4 import BeautifulSoup

class MNRECrawler:
    def __init__(self):
        # Target URLs for Solar Regulatory Infrastructure
        self.targets = {
            "solar_policy": "https://mnre.gov.in/en/solar-policies-and-guidelines/",
            "schemes": "https://mnre.gov.in/en/policies-and-regulations/schemes-and-guidelines/schemes/",
            "almm": "https://mnre.gov.in/en/approved-list-of-models-and-manufacturers-almm/"
        }

    def parse_document_table(self, html_content: str):
        """
        Parses the standard MNRE document table.
        Returns a list of dicts: {'title', 'date', 'link'}
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        documents = []
        
        # MNRE tables usually have a standard 'table' tag or class
        table = soup.find('table')
        if not table:
            return []

        rows = table.find_all('tr')[1:]  # Skip header row
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 3:
                title = cols[0].get_text(strip=True)
                date_str = cols[1].get_text(strip=True)
                
                # Extract PDF link - Look for the 'View' link
                link_tag = cols[2].find('a', href=True)
                link = str(link_tag['href']) if link_tag else None
                
                if link and not link.startswith('http'):
                    link = f"https://mnre.gov.in{link}"

                # Parse date for sorting (Handles DD/MM/YYYY)
                try:
                    date_obj = datetime.strptime(date_str, '%d/%m/%Y')
                except ValueError:
                    date_obj = datetime.min # Fallback for undated docs

                documents.append({
                    "title": title,
                    "date": date_obj,
                    "link": link
                })
        
        # Sort by date descending (Newest first)
        return sorted(documents, key=lambda x: x['date'], reverse=True)

# Example Usage logic for main.py integration:
# crawler = MNRECrawler()
# newest_docs = crawler.parse_document_table(raw_html_from_crawl4ai)