"""
bj_onpb.py — Scraper Bénin : onpb.bj (tour de garde)
======================================================
Source : https://onpb.bj/category/tour-de-garde/
Données publiées sous forme d'images JPEG (captures WhatsApp).

Pipeline :
  1. Pagination /category/tour-de-garde/page/N/
  2. Collecte des URLs d'images dans chaque article
  3. Téléchargement + prétraitement (PIL) + OCR (EasyOCR)
  4. Extraction regex → {name, city_name, phone, ...}
  5. Sync MongoDB (countries → cities → pharmacies)
"""

import os
import re
import json
import logging
from io import BytesIO

import httpx
from bs4 import BeautifulSoup
from PIL import Image, ImageEnhance, ImageFilter

from app.worker.base_scraper import BaseScraper
from app.worker.scraper_registry import register_scraper

log = logging.getLogger("pharmaco.scraper.bj_onpb")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

LISTING_URL = "https://onpb.bj/category/tour-de-garde/"
MAX_PAGES   = 30  # sécurité anti-boucle infinie

# ── OCR reader (chargé une seule fois au premier appel) ────────────────────────
_ocr_reader = None


def _get_reader():
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr  # import tardif : lourd à charger
        model_dir = os.environ.get("EASYOCR_MODULE_PATH", os.path.expanduser("~/.EasyOCR"))
        log.info("[BJ/onpb] Initialisation EasyOCR (modèles : %s)…", model_dir)
        _ocr_reader = easyocr.Reader(
            ["fr", "en"], gpu=False, verbose=False,
            model_storage_directory=model_dir,
        )
    return _ocr_reader


# ── Traitement image ───────────────────────────────────────────────────────────

def _preprocess(img_bytes: bytes) -> bytes:
    """Niveaux de gris + contraste amélioré + netteté → meilleur taux OCR."""
    img = Image.open(BytesIO(img_bytes)).convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.filter(ImageFilter.SHARPEN)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _run_ocr(img_bytes: bytes) -> str:
    """Retourne le texte extrait d'une image."""
    processed = _preprocess(img_bytes)
    results   = _get_reader().readtext(processed, detail=0, paragraph=True)
    return "\n".join(results)


# ── Parsing texte OCR ──────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\u00a0", " ")).strip()


# Numéros de téléphone béninois : 8 chiffres, éventuellement précédés de +229
_PHONE_RE = re.compile(r"(\+?2?2?9?\s?\d[\d\s\-\.]{5,11}\d)")

# Lignes à ignorer (en-têtes, mentions légales, etc.)
_SKIP_RE = re.compile(
    r"programme|tour\s+de\s+garde|semaine|ordre\s+national|"
    r"pharmaciens|b[eé]nin|publi[eé]|publish|page\s+\d|©|\bwww\b",
    re.I,
)


def _is_city_candidate(line: str) -> bool:
    """Ligne courte sans téléphone ni mot 'pharma' → probable nom de ville."""
    return (
        len(line) <= 30
        and not re.search(r"pharm", line, re.I)
        and not _PHONE_RE.search(line)
    )


def _extract_pharmacy(line: str, current_city: str) -> dict | None:
    """
    Tente d'extraire un dict pharmacie depuis une ligne OCR.
    Retourne None si la ligne ne correspond pas à une pharmacie.
    """
    if not re.search(r"pharm", line, re.I):
        return None

    phone_m   = _PHONE_RE.search(line)
    phone     = re.sub(r"[\s\-\.]", "", phone_m.group(1)) if phone_m else None
    name_part = _PHONE_RE.sub("", line).strip(" -|/,") if phone_m else line

    parts = [p.strip() for p in re.split(r"\s*[-|,]\s*", name_part) if p.strip()]
    name  = _clean(parts[0]) if parts else None

    city = current_city
    if len(parts) >= 2:
        last = parts[-1].upper()
        if not re.search(r"pharm", last, re.I):
            city = last

    if not name or not city:
        return None

    return {
        "name":         name,
        "contact_name": None,
        "address":      None,
        "city_name":    city,
        "phone":        phone,
    }


def _parse_ocr_text(text: str, default_city: str = "") -> list[dict]:
    """
    Parse le texte OCR ligne par ligne.

    Heuristiques :
      • Ligne courte sans "pharma" et sans téléphone  → probable nom de ville
      • Ligne contenant "pharma"                      → enregistrement pharmacie
    """
    pharmacies:  list[dict] = []
    seen:        set[tuple] = set()
    current_city = default_city.upper()

    for raw_line in text.splitlines():
        line = _clean(raw_line)
        if not line or len(line) < 6 or _SKIP_RE.search(line):
            continue

        if _is_city_candidate(line):
            candidate = re.sub(r"[^A-Za-zÀ-ÿ\s-]", "", line).strip().upper()
            if len(candidate) >= 3:
                current_city = candidate
            continue

        pharmacy = _extract_pharmacy(line, current_city)
        if pharmacy is None:
            continue

        key = (pharmacy["name"].lower(), pharmacy["city_name"])
        if key not in seen:
            seen.add(key)
            pharmacies.append(pharmacy)

    return pharmacies


# ── Scraper ────────────────────────────────────────────────────────────────────

@register_scraper
class OnpbBeninScraper(BaseScraper):
    """
    Scraper Bénin — source ONPB (onpb.bj).
    Remplace UbpharBeninScraper (bj_ubphar.py, désactivé).
    """

    country_code = "BJ"
    country_name = "Bénin"
    source_url   = LISTING_URL
    source_name  = "onpb"

    # ── fetch ─────────────────────────────────────────────────────────────────

    async def fetch(self) -> str:
        """
        Pagine /category/tour-de-garde/ et collecte les URLs des images
        contenues dans chaque article de garde.

        Retourne : JSON  [{"img_url": "...", "region": "..."}, ...]
        """
        image_refs: list[dict] = []

        async with httpx.AsyncClient(
            headers=HEADERS, follow_redirects=True, timeout=30
        ) as client:
            articles = await self._collect_articles(client)
            log.info("[BJ/onpb] %d articles collectés", len(articles))

            for art_url, region in articles:
                try:
                    resp = await client.get(art_url)
                    resp.raise_for_status()
                    soup    = BeautifulSoup(resp.text, "lxml")
                    content = soup.find(
                        "div", class_=re.compile(r"entry-content|post-content")
                    )
                    if not content:
                        continue
                    for img in content.find_all("img"):
                        src = img.get("src", "").strip()
                        if src:
                            image_refs.append({"img_url": src, "region": region})
                except Exception as exc:
                    log.warning("[BJ/onpb] article ignoré (%s) : %s", art_url, exc)

        log.info("[BJ/onpb] %d images à traiter via OCR", len(image_refs))
        return json.dumps(image_refs)

    async def _collect_articles(
        self, client: httpx.AsyncClient
    ) -> list[tuple[str, str]]:
        """Retourne [(url_article, region), ...] en paginant la catégorie."""
        articles: list[tuple[str, str]] = []
        seen:     set[str]              = set()

        for page in range(1, MAX_PAGES + 1):
            url = LISTING_URL if page == 1 else f"{LISTING_URL}page/{page}/"
            try:
                resp = await client.get(url)
                if resp.status_code == 404:
                    break
                resp.raise_for_status()
            except Exception as exc:
                log.warning("[BJ/onpb] pagination arrêtée page %d : %s", page, exc)
                break

            soup  = BeautifulSoup(resp.text, "lxml")
            links = soup.find_all("a", href=re.compile(r"/programme-de-garde-"))

            new = 0
            for a in links:
                href = a.get("href", "")
                if href and href not in seen:
                    seen.add(href)
                    articles.append((href, self._region_from_url(href)))
                    new += 1

            if new == 0:
                break  # plus de nouveaux liens → fin de pagination

        return articles

    @staticmethod
    def _region_from_url(url: str) -> str:
        """Extrait la région depuis le slug d'URL."""
        m = re.search(r"/programme-de-garde-(.+?)-du-", url)
        return m.group(1).replace("-", " ").upper() if m else ""

    # ── parse ─────────────────────────────────────────────────────────────────

    def parse(self, raw: str) -> list[dict]:
        """
        Pour chaque image référencée dans le JSON :
          1. Téléchargement (httpx sync)
          2. Prétraitement PIL
          3. OCR EasyOCR
          4. Extraction regex → dict pharmacie
        """
        image_refs: list[dict]   = json.loads(raw)
        all_pharmacies: list[dict] = []
        global_seen: set[tuple]   = set()

        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30) as client:
            for i, item in enumerate(image_refs, start=1):
                try:
                    resp = client.get(item["img_url"])
                    resp.raise_for_status()

                    text = _run_ocr(resp.content)
                    log.debug(
                        "[BJ/onpb] Image %d/%d — région=%s\n%s",
                        i, len(image_refs), item["region"], text,
                    )

                    for p in _parse_ocr_text(text, default_city=item["region"]):
                        key = (p["name"].lower(), p["city_name"])
                        if key not in global_seen:
                            global_seen.add(key)
                            all_pharmacies.append(p)

                except Exception as exc:
                    log.warning("[BJ/onpb] image %d ignorée : %s", i, exc)

        log.info("[BJ/onpb] %d pharmacies uniques extraites (OCR)", len(all_pharmacies))
        return all_pharmacies
