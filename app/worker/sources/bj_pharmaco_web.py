"""
bj_pharmaco_web.py — Scraper Bénin : pharmaco-web-source (Railway)
==================================================================
Source : https://pharmaco-web-source-production.up.railway.app

Pipeline :
  1. Téléchargement de la page HTML
  2. Extraction du tableau JS  `const PHARMACIES = [{...}, ...]`
  3. Parse regex champ par champ (nom, contact, ville, tel)
  4. Sync MongoDB (countries → cities → pharmacies)

Champs disponibles : nom · contact · ville · tel
"""

import re
import logging

import httpx

from app.worker.base_scraper import BaseScraper
from app.worker.scraper_registry import register_scraper

log = logging.getLogger("pharmaco.scraper.bj_pharmaco_web")

SOURCE_URL = "https://pharmaco-web-source-production.up.railway.app"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}


def _get_field(obj_str: str, field: str) -> str | None:
    """Extrait la valeur d'un champ JS  `field: "valeur"` depuis un bloc d'objet."""
    m = re.search(rf'\b{field}\s*:\s*"([^"]*)"', obj_str)
    return m.group(1).strip() if m else None


@register_scraper
class PharmacoWebBeninScraper(BaseScraper):
    """
    Scraper Bénin — source pharmaco-web (Railway).
    Complémentaire au scraper ONPB (bj_onpb.py).
    """

    country_code = "BJ"
    country_name = "Bénin"
    source_url   = SOURCE_URL
    source_name  = "pharmaco_web"

    # ── fetch ──────────────────────────────────────────────────────
    async def fetch(self) -> str:
        """Télécharge la page HTML contenant le tableau JS PHARMACIES."""
        async with httpx.AsyncClient(
            headers=HEADERS, follow_redirects=True, timeout=30
        ) as client:
            resp = await client.get(SOURCE_URL)
            resp.raise_for_status()
            return resp.text

    # ── parse ──────────────────────────────────────────────────────
    def parse(self, raw: str) -> list[dict]:
        """
        Extrait le tableau  `const PHARMACIES = [{...}, ...]`
        et retourne une liste de dicts pharmacie.
        """
        m = re.search(r'const\s+PHARMACIES\s*=\s*\[(.+?)\]\s*;', raw, re.DOTALL)
        if not m:
            log.warning("[BJ/pharmaco_web] Tableau PHARMACIES introuvable dans le HTML.")
            return []

        array_content = m.group(1)
        pharmacies: list[dict] = []

        for obj_match in re.finditer(r'\{([^}]+)\}', array_content, re.DOTALL):
            obj_str = obj_match.group(1)

            name = _get_field(obj_str, "nom")
            if not name:
                continue

            city = (_get_field(obj_str, "ville") or "").upper().strip()
            if not city:
                continue

            pharmacies.append({
                "name":         name,
                "contact_name": _get_field(obj_str, "contact"),
                "address":      None,
                "city_name":    city,
                "phone":        _get_field(obj_str, "tel"),
            })

        log.info("[BJ/pharmaco_web] %d pharmacies extraites", len(pharmacies))
        return pharmacies
