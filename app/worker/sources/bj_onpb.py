"""
bj_onpb.py — Scraper Bénin : onpb.bj (tour de garde)
======================================================
Source : https://onpb.bj/category/tour-de-garde/

Pipeline :
  1. Pagination /category/tour-de-garde/page/N/
  2. Collecte des URLs d'images dans chaque article
  3. Téléchargement + prétraitement PIL + OCR (Tesseract)
  4. Détection du format par département (5 formats distincts)
  5. Extraction structurée → {name, city_name, phone, address, ...}
  6. Sync MongoDB (countries → cities → pharmacies)

Formats par département :
  FORMAT_A  ZOU, COLLINES, MONO, COUFFO
            colonnes : PHARMACIE | LOCALITE | TELEPHONE
            city     : colonne VILLE/ARR

  FORMAT_B  ATACORA, DONGA, BORGOU, ALIBORI
            lignes alternées : contact_name (noir) / name (vert)
            phone    : Téléphone pharmacie
            city     : ligne standalone

  FORMAT_C  LITTORAL
            colonnes : NOM DE LA PHARMACIE | QUARTIER | TELEPHONE
            city     : ligne d'en-tête horizontale

  FORMAT_D  ATLANTIQUE
            colonnes : NOM DE PHARMACIE | QUARTIER | TELEPHONE
            city     : ligne d'en-tête horizontale

  FORMAT_E  OUEME, PLATEAU
            colonnes : PHARMACIE | QUARTIER | CONTACT
            city     : colonne REGION
            alt      : "NomPharmacie Tél:0000000"
"""

import re
import json
import time
import logging
from enum import Enum, auto
from io import BytesIO

import httpx
from bs4 import BeautifulSoup
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract

from app.worker.base_scraper import BaseScraper
from app.worker.scraper_registry import register_scraper

log = logging.getLogger("pharmaco.scraper.bj_onpb")

# ── Constantes ────────────────────────────────────────────────────
LISTING_URL = "https://onpb.bj/category/tour-de-garde/"
MAX_PAGES   = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Connection":      "keep-alive",
}

# ── Détection de format ───────────────────────────────────────────
class Fmt(Enum):
    A = auto()  # ZOU / COLLINES / MONO / COUFFO
    B = auto()  # ATACORA / DONGA / BORGOU / ALIBORI
    C = auto()  # LITTORAL
    D = auto()  # ATLANTIQUE
    E = auto()  # OUEME / PLATEAU
    UNKNOWN = auto()

# Mots-clés dans le slug d'URL → format
_SLUG_TO_FMT: dict[str, Fmt] = {
    "zou":        Fmt.A,
    "collines":   Fmt.A,
    "mono":       Fmt.A,
    "couffo":     Fmt.A,
    "atacora":    Fmt.B,
    "donga":      Fmt.B,
    "borgou":     Fmt.B,
    "alibori":    Fmt.B,
    "littoral":   Fmt.C,
    "cotonou":    Fmt.C,
    "atlantique": Fmt.D,
    "oueme":      Fmt.E,
    "plateau":    Fmt.E,
}

# En-têtes caractéristiques dans le texte OCR → format
_HEADER_PATTERNS: list[tuple[re.Pattern, Fmt]] = [
    (re.compile(r"LOCALITE",                    re.I), Fmt.A),
    (re.compile(r"PHARMACIE\s+NOM",             re.I), Fmt.B),
    (re.compile(r"NOM\s+DE\s+LA\s+PHARMACIE",  re.I), Fmt.C),
    (re.compile(r"NOM\s+DE\s+PHARMACIE",        re.I), Fmt.D),
    (re.compile(r"CONTACT\b",                   re.I), Fmt.E),
]


def _detect_format(region_slug: str, ocr_text: str) -> Fmt:
    """Détermine le format à partir du slug d'URL puis du texte OCR."""
    slug_lower = region_slug.lower()
    for kw, fmt in _SLUG_TO_FMT.items():
        if kw in slug_lower:
            return fmt

    # Fallback : inspection des en-têtes dans le texte OCR
    for pattern, fmt in _HEADER_PATTERNS:
        if pattern.search(ocr_text):
            return fmt

    return Fmt.UNKNOWN


# ── Prétraitement image + OCR ─────────────────────────────────────
def _preprocess(img_bytes: bytes, scale: int = 2) -> Image.Image:
    """
    Niveaux de gris → agrandissement → contraste → netteté.
    scale=2 double la résolution (améliore Tesseract sur petits textes).
    """
    img = Image.open(BytesIO(img_bytes)).convert("L")
    w, h = img.size
    img = img.resize((w * scale, h * scale), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = ImageEnhance.Sharpness(img).enhance(2.0)
    return img.filter(ImageFilter.SHARPEN)


def _ocr(img_bytes: bytes) -> str:
    """Lance Tesseract (langue française) et retourne le texte brut."""
    img = _preprocess(img_bytes)
    cfg = r"--oem 3 --psm 6 -l fra"
    return pytesseract.image_to_string(img, config=cfg)


# ── Utilitaires communs ───────────────────────────────────────────
def _clean(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s.replace("\u00a0", " ")).strip()

# Numéros béninois : 8 chiffres (éventuellement avec +229 ou espaces)
_PHONE_RE = re.compile(r"(\+?229\s?)?(\d[\d\s/\-\.]{5,12}\d)")

def _extract_phone(text: str) -> str | None:
    m = _PHONE_RE.search(text)
    if not m:
        return None
    raw = m.group(0)
    digits = re.sub(r"[^\d+]", "", raw)
    return digits if len(digits) >= 8 else None

def _remove_phone(text: str) -> str:
    return _PHONE_RE.sub("", text).strip(" -|/,;")

# Lignes à ignorer (en-têtes, pieds de page, mentions légales)
_IGNORE_RE = re.compile(
    r"programme|tour\s+de\s+garde|semaine|ordre\s+national|pharmacien|"
    r"publi|©|www\.|page\s*\d|tel[eé]phone|contact|pharmacie\s+nom|"
    r"nom\s+de\s+(la\s+)?pharmacie|quartier|localite|r[eé]gion|arr[oô]ndissement",
    re.I,
)

def _is_header_or_skip(line: str) -> bool:
    return bool(_IGNORE_RE.search(line)) or len(line.strip()) < 4

def _make_entry(name: str, city: str, phone: str | None,
                address: str | None = None,
                contact: str | None = None) -> dict | None:
    name = _clean(name)
    city = _clean(city).upper()
    if not name or not city:
        return None
    if re.match(r"^(NOM|PHARMACIE|TELEPHONE|CONTACT|QUARTIER|LOCALITE|REGION)\s*$", name, re.I):
        return None
    return {
        "name":         name,
        "contact_name": _clean(contact) or None,
        "address":      _clean(address) or None,
        "city_name":    city,
        "phone":        phone,
    }


# ═════════════════════════════════════════════════════════════════
# Parsers spécialisés par format
# ═════════════════════════════════════════════════════════════════

def _parse_format_a(lines: list[str]) -> list[dict]:
    """
    FORMAT A — ZOU / COLLINES / MONO / COUFFO
    Colonnes attendues : PHARMACIE | LOCALITE (adresse) | VILLE/ARR (city) | TELEPHONE
    """
    results = []
    current_city = ""

    for line in lines:
        if _is_header_or_skip(line):
            if (len(line) <= 30
                    and not _PHONE_RE.search(line)
                    and not re.search(r"pharm", line, re.I)):
                candidate = re.sub(r"[^A-Za-zÀ-ÿ\s\-]", "", line).strip().upper()
                if len(candidate) >= 3:
                    current_city = candidate
            continue

        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:
                name    = parts[0]
                address = parts[1] if len(parts) >= 4 else None
                city    = parts[-2] if len(parts) >= 4 else current_city
                phone   = _extract_phone(parts[-1])
                if not city:
                    city = current_city
                e = _make_entry(name, city, phone, address)
                if e:
                    results.append(e)
                continue

        if re.search(r"pharm", line, re.I):
            phone = _extract_phone(line)
            name  = _remove_phone(line)
            e = _make_entry(name, current_city, phone)
            if e:
                results.append(e)

    return results


def _parse_format_b(lines: list[str]) -> list[dict]:
    """
    FORMAT B — ATACORA / DONGA / BORGOU / ALIBORI
    Structure par bloc de 2-3 lignes :
      ligne 1 : contact_name (texte noir)
      ligne 2 : name         (texte vert)
      ligne 3 : phone
    """
    results      = []
    current_city = ""
    i            = 0

    while i < len(lines):
        line = lines[i]

        if _is_header_or_skip(line):
            if (len(line) <= 35
                    and not _PHONE_RE.search(line)
                    and not re.search(r"pharm", line, re.I)):
                candidate = re.sub(r"[^A-Za-zÀ-ÿ\s\-]", "", line).strip().upper()
                if len(candidate) >= 3:
                    current_city = candidate
            i += 1
            continue

        has_pharm  = re.search(r"pharm", line, re.I)
        phone_here = _extract_phone(line)

        if has_pharm or phone_here:
            candidate_name    = _remove_phone(line) if phone_here else line
            candidate_contact = None
            phone             = phone_here

            if i + 1 < len(lines) and re.search(r"pharm", lines[i + 1], re.I):
                candidate_contact = candidate_name
                candidate_name    = lines[i + 1]
                i += 1

            if not phone:
                for j in range(i + 1, min(i + 3, len(lines))):
                    p = _extract_phone(lines[j])
                    if p:
                        phone = p
                        i = j
                        break

            e = _make_entry(candidate_name, current_city, phone, contact=candidate_contact)
            if e:
                results.append(e)

        i += 1

    return results


def _parse_format_c_d(lines: list[str], fmt: Fmt) -> list[dict]:
    """
    FORMAT C (LITTORAL) et FORMAT D (ATLANTIQUE)
    Colonnes : NOM PHARMACIE | QUARTIER | TELEPHONE
    City      : ligne d'en-tête horizontale all-caps
    """
    results      = []
    current_city = ""

    for line in lines:
        if (not re.search(r"pharm", line, re.I)
                and not _PHONE_RE.search(line)
                and len(line.strip()) <= 40
                and re.search(r"[A-ZÀÉÈÊ]{3,}", line)):
            candidate = re.sub(r"[^A-Za-zÀ-ÿ\s\-]", "", line).strip().upper()
            if len(candidate) >= 3 and not _IGNORE_RE.search(candidate):
                current_city = candidate
                continue

        if _is_header_or_skip(line):
            continue

        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                name    = parts[0]
                address = parts[1] if len(parts) >= 3 else None
                phone   = _extract_phone(parts[-1]) if len(parts) >= 2 else None
                e = _make_entry(name, current_city, phone, address)
                if e:
                    results.append(e)
                continue

        if re.search(r"pharm", line, re.I):
            phone  = _extract_phone(line)
            name   = _remove_phone(line)
            parts  = re.split(r"\s{2,}", name)
            address = _clean(parts[-1]) if len(parts) > 1 else None
            name   = parts[0]
            e = _make_entry(name, current_city, phone, address)
            if e:
                results.append(e)

    return results


def _parse_format_e(lines: list[str]) -> list[dict]:
    """
    FORMAT E — OUEME / PLATEAU
    Colonnes : PHARMACIE | QUARTIER | CONTACT
    City      : colonne REGION (ligne standalone all-caps)
    Alt       : "Nom Pharmacie Tél:0101010101"
    """
    results      = []
    current_city = ""

    for line in lines:
        if _is_header_or_skip(line):
            if (len(line) <= 35
                    and not _PHONE_RE.search(line)
                    and not re.search(r"pharm|tél|tel\b", line, re.I)):
                candidate = re.sub(r"[^A-Za-zÀ-ÿ\s\-]", "", line).strip().upper()
                if len(candidate) >= 3:
                    current_city = candidate
            continue

        tél_match = re.search(r"[Tt][eé]l\s*[:\.]?\s*(\d[\d\s/\-\.]{5,12}\d)", line)
        if tél_match:
            phone = re.sub(r"[^\d]", "", tél_match.group(1))
            name  = re.sub(r"\s*[Tt][eé]l\s*[:\.]?\s*\d[\d\s/\-\.]*\d", "", line).strip()
            e = _make_entry(name, current_city, phone if len(phone) >= 8 else None)
            if e:
                results.append(e)
            continue

        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                name    = parts[0]
                city    = parts[1] if len(parts) >= 3 and not re.search(r"\d{6,}", parts[1]) else current_city
                phone   = _extract_phone(parts[-1])
                address = parts[1] if city == current_city and len(parts) >= 3 else None
                e = _make_entry(name, city or current_city, phone, address)
                if e:
                    results.append(e)
                continue

        if re.search(r"pharm", line, re.I):
            phone = _extract_phone(line)
            name  = _remove_phone(line)
            e = _make_entry(name, current_city, phone)
            if e:
                results.append(e)

    return results


def _parse_unknown(lines: list[str]) -> list[dict]:
    """Fallback générique : extrait toute ligne contenant 'pharm'."""
    results      = []
    current_city = ""

    for line in lines:
        if (not re.search(r"pharm", line, re.I)
                and len(line) <= 30
                and not _PHONE_RE.search(line)):
            candidate = re.sub(r"[^A-Za-zÀ-ÿ\s\-]", "", line).strip().upper()
            if len(candidate) >= 3 and not _IGNORE_RE.search(candidate):
                current_city = candidate
            continue

        if re.search(r"pharm", line, re.I):
            phone = _extract_phone(line)
            name  = _remove_phone(line)
            e = _make_entry(name, current_city, phone)
            if e:
                results.append(e)

    return results


def _dispatch(fmt: Fmt, ocr_text: str) -> list[dict]:
    """Choisit le parser selon le format détecté et retourne les entrées."""
    lines = [_clean(l) for l in ocr_text.splitlines() if _clean(l)]

    if fmt == Fmt.A:
        return _parse_format_a(lines)
    if fmt == Fmt.B:
        return _parse_format_b(lines)
    if fmt in (Fmt.C, Fmt.D):
        return _parse_format_c_d(lines, fmt)
    if fmt == Fmt.E:
        return _parse_format_e(lines)
    return _parse_unknown(lines)


# ═════════════════════════════════════════════════════════════════
# Scraper principal
# ═════════════════════════════════════════════════════════════════

@register_scraper
class OnpbBeninScraper(BaseScraper):
    """
    Scraper Bénin — source ONPB (onpb.bj).
    Remplace UbpharBeninScraper.
    """

    country_code = "BJ"
    country_name = "Bénin"
    source_url   = LISTING_URL
    source_name  = "onpb"

    # ── fetch ──────────────────────────────────────────────────────
    async def fetch(self) -> str:
        """
        Pagine la catégorie et collecte les URLs d'images avec leurs métadonnées.
        Retourne un JSON :  [{"img_url": "...", "region": "...", "fmt_hint": "A"}, ...]
        """
        image_refs: list[dict] = []

        async with httpx.AsyncClient(
            headers=HEADERS, follow_redirects=True, timeout=30
        ) as client:
            articles = await self._collect_articles(client)
            log.info("[BJ/onpb] %d articles trouvés", len(articles))

            for art_url, region, fmt in articles:
                try:
                    resp = await client.get(art_url)
                    resp.raise_for_status()
                    soup    = BeautifulSoup(resp.text, "lxml")
                    content = soup.find(
                        "div",
                        class_=re.compile(r"entry-content|post-content|article-content"),
                    )
                    if not content:
                        continue
                    for img in content.find_all("img"):
                        src = (img.get("data-src") or img.get("src") or "").strip()
                        if src and re.search(r"\.(jpe?g|png|webp)", src, re.I):
                            image_refs.append({
                                "img_url":  src,
                                "region":   region,
                                "fmt_hint": fmt.name,
                            })
                except Exception as exc:
                    log.warning("[BJ/onpb] article ignoré (%s) : %s", art_url, exc)

        log.info("[BJ/onpb] %d images à traiter", len(image_refs))
        return json.dumps(image_refs)

    async def _collect_articles(
        self, client: httpx.AsyncClient
    ) -> list[tuple[str, str, Fmt]]:
        articles: list[tuple[str, str, Fmt]] = []
        seen: set[str] = set()

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
            links = soup.find_all("a", href=re.compile(r"/programme-de-garde-|/tour-de-garde-"))

            new = 0
            for a in links:
                href = (a.get("href") or "").strip()
                if href and href not in seen:
                    seen.add(href)
                    region = self._region_from_url(href)
                    fmt    = _detect_format(region, "")
                    articles.append((href, region, fmt))
                    new += 1

            if new == 0:
                break

        return articles

    @staticmethod
    def _fetch_with_retry(url: str, max_attempts: int = 3) -> bytes | None:
        """
        Télécharge une image avec retry + backoff exponentiel.
        Recrée un nouveau client à chaque tentative pour éviter
        les connexions mortes après un Server disconnect.
        """
        for attempt in range(1, max_attempts + 1):
            try:
                with httpx.Client(
                    headers=HEADERS, follow_redirects=True, timeout=30
                ) as client:
                    resp = client.get(url)
                    resp.raise_for_status()
                    return resp.content
            except Exception as exc:
                wait = 2 ** attempt  # 2s, 4s, 8s
                if attempt < max_attempts:
                    log.warning(
                        "[BJ/onpb] %s — tentative %d/%d, retry dans %ds : %s",
                        url.split("/")[-1], attempt, max_attempts, wait, exc,
                    )
                    time.sleep(wait)
                else:
                    log.warning("[BJ/onpb] image ignorée après %d tentatives : %s",
                                max_attempts, exc)
        return None

    @staticmethod
    def _region_from_url(url: str) -> str:
        """Extrait le département/région depuis le slug."""
        patterns = [
            r"/programme-de-garde-(.+?)-(?:du|semaine|de)-",
            r"/tour-de-garde-(.+?)-",
        ]
        for pat in patterns:
            m = re.search(pat, url)
            if m:
                return m.group(1).replace("-", " ").upper()
        return ""

    # ── parse ──────────────────────────────────────────────────────
    def parse(self, raw: str) -> list[dict]:
        """
        Pour chaque image :
          1. Téléchargement
          2. OCR Tesseract
          3. Détection du format (slug + inspection des en-têtes OCR)
          4. Parser spécialisé
          5. Déduplication globale
        """
        image_refs: list[dict]     = json.loads(raw)
        all_pharmacies: list[dict] = []
        global_seen: set[tuple]    = set()
        fmt_stats: dict[str, int]  = {}

        for i, item in enumerate(image_refs, start=1):
            img_bytes = self._fetch_with_retry(item["img_url"])
            if img_bytes is None:
                continue

            try:
                text = _ocr(img_bytes)
                fmt  = _detect_format(item["region"], text)
                fmt_stats[fmt.name] = fmt_stats.get(fmt.name, 0) + 1

                log.debug(
                    "[BJ/onpb] Image %d/%d region=%s fmt=%s",
                    i, len(image_refs), item["region"], fmt.name,
                )

                for p in _dispatch(fmt, text):
                    key = (p["name"].lower(), p["city_name"])
                    if key not in global_seen:
                        global_seen.add(key)
                        all_pharmacies.append(p)

            except Exception as exc:
                log.warning("[BJ/onpb] OCR image %d/%d échouée : %s",
                            i, len(image_refs), exc)

            time.sleep(0.8)  # délai entre images pour éviter le rate limiting

        log.info(
            "[BJ/onpb] Terminé — %d pharmacies uniques | formats: %s",
            len(all_pharmacies),
            ", ".join(f"{k}:{v}" for k, v in sorted(fmt_stats.items())),
        )
        return all_pharmacies
