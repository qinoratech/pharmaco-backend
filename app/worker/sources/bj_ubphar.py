"""
bj_ubphar.py — Scraper Bénin : ubphar.com
==========================================
Source officielle : https://www.ubphar.com/content/ubphar/liste-des-pharmacies
Tableau HTML : Nom | Contact | Adresse | Ville | Téléphone
"""

import re
import logging
import httpx
from bs4 import BeautifulSoup

from app.worker.base_scraper import BaseScraper
from app.worker.scraper_registry import register_scraper

log = logging.getLogger("pharmaco.scraper.bj_ubphar")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PharmacoBotBJ/1.0; +https://pharmaco.bj/bot)",
    "Accept-Language": "fr-FR,fr;q=0.9",
}


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ").replace("\xa0", " ")).strip()


def _primary_phone(raw: str) -> str:
    """Garde uniquement le premier numéro ('21321565 / 97981671' → '21321565')."""
    parts = [p.strip() for p in raw.split("/") if p.strip()]
    return parts[0] if parts else ""


@register_scraper
class UbpharBeninScraper(BaseScraper):
    country_code = "BJ"
    country_name = "Bénin"
    source_url   = "https://www.ubphar.com/content/ubphar/liste-des-pharmacies"
    source_name  = "ubphar"

    async def fetch(self) -> str:
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as client:
            resp = await client.get(self.source_url)
            resp.raise_for_status()
            return resp.text

    def parse(self, raw: str) -> list[dict]:
        soup = BeautifulSoup(raw, "lxml")
        table = soup.find("table")
        if not table:
            log.warning("Aucun tableau trouvé sur la page ubphar")
            return []

        pharmacies = []
        for row in table.find_all("tr")[1:]:
            cols = row.find_all("td")
            if len(cols) < 5:
                continue

            name         = _clean(cols[0].get_text())
            contact_name = _clean(cols[1].get_text())
            address      = _clean(cols[2].get_text())
            city_name    = _clean(cols[3].get_text()).upper()
            phone        = _primary_phone(_clean(cols[4].get_text()))

            if not name or not city_name:
                continue

            pharmacies.append({
                "name":         name,
                "contact_name": contact_name or None,
                "address":      address or None,
                "city_name":    city_name,
                "phone":        phone or None,
            })

        log.info("ubphar — %d pharmacies parsées", len(pharmacies))
        return pharmacies
