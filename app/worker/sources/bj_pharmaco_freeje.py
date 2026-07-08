"""
bj_pharmaco_freeje.py — Scraper Bénin : pharmaco.free.je
=========================================================
Source : https://pharmaco.free.je/pharmaco/pages/pharmacies.php

Cette source expose une liste structurée de pharmacies (nom, ville,
département, GPS, statut de garde) directement dans le HTML : chaque
carte embarque un objet JSON dans son `onclick="ouvrirModalDetail({...})"`.

Pipeline :
  1. Résolution du challenge anti-bot JavaScript (free.je)
     → la 1re requête renvoie un script `slowAES.decrypt(c, 2, a, b)`
       qui pose un cookie `__test`. On le reproduit en AES-128-CBC.
  2. Pagination `?filtre=toutes&page=N` jusqu'à épuisement.
  3. Extraction des objets JSON par regex + json.loads.
  4. Sync MongoDB (countries → cities → pharmacies) via BaseScraper.

Champs disponibles : nom · ville (zone) · adresse · département ·
                     latitude · longitude · en_garde
Non fourni par la source : téléphone (vide à ce jour).
"""

import re
import json
import html as html_lib
import logging

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.worker.base_scraper import BaseScraper
from app.worker.scraper_registry import register_scraper

log = logging.getLogger("pharmaco.scraper.bj_pharmaco_freeje")

# Host SANS "www" : le certificat TLS couvre *.free.je (donc pharmaco.free.je
# est valide) mais PAS www.pharmaco.free.je (4e niveau). On garde ainsi la
# vérification TLS activée.
BASE      = "https://pharmaco.free.je/pharmaco/pages/pharmacies.php"
MAX_PAGES = 80  # garde-fou (413 pharmacies ≈ 42 pages de 10 à ce jour)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

# Objet JSON embarqué dans chaque carte pharmacie
_OBJ_RE       = re.compile(r"ouvrirModalDetail\((\{.*?\})\)")
# Valeurs hexadécimales du challenge AES : var a=toNumbers("..."),b=...,c=...
_CHALLENGE_RE = re.compile(r'toNumbers\("([0-9a-fA-F]+)"\)')


def _solve_challenge(page_html: str) -> str | None:
    """
    Reproduit `toHex(slowAES.decrypt(c, 2, a, b))` du script anti-bot :
    déchiffrement AES-128-CBC (clé=a, iv=b) du bloc c, puis hex.
    Retourne la valeur du cookie `__test`, ou None si illisible.
    """
    vals = _CHALLENGE_RE.findall(page_html)
    if len(vals) < 3:
        return None
    key, iv, ciphertext = (bytes.fromhex(v) for v in vals[:3])
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    return plaintext.hex()


def _to_float(value) -> float | None:
    """Convertit une coordonnée en float ; None si absente ou nulle (~0)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if abs(f) > 0.1 else None


@register_scraper
class PharmacoFreejeBeninScraper(BaseScraper):
    """Scraper Bénin — source pharmaco.free.je (liste structurée + GPS + garde)."""

    country_code = "BJ"
    country_name = "Bénin"
    source_url   = BASE
    source_name  = "pharmaco_freeje"

    # ── fetch ──────────────────────────────────────────────────────
    async def fetch(self) -> str:
        """
        Résout le challenge anti-bot puis pagine `?filtre=toutes`.
        Retourne un JSON : liste brute des objets pharmacie de la source.
        """
        async with httpx.AsyncClient(
            headers=HEADERS, follow_redirects=True, timeout=30
        ) as client:
            # 1. Challenge anti-bot (cookie __test)
            resp = await client.get(BASE)
            resp.raise_for_status()
            if "slowAES" in resp.text or "toNumbers" in resp.text:
                cookie = _solve_challenge(resp.text)
                if not cookie:
                    log.error("[BJ/freeje] Challenge AES illisible — abandon.")
                    return "[]"
                client.cookies.set("__test", cookie, domain="pharmaco.free.je", path="/")
                log.info("[BJ/freeje] Challenge anti-bot résolu.")

            # 2. Pagination filtre=toutes
            collected: dict[int, dict] = {}
            last_page = 0
            for page in range(1, MAX_PAGES + 1):
                last_page = page
                r = await client.get(BASE, params={"filtre": "toutes", "page": page})
                if r.status_code != 200:
                    break
                raw  = html_lib.unescape(r.text)
                objs = _OBJ_RE.findall(raw)
                if not objs:
                    break

                new = 0
                for obj_str in objs:
                    try:
                        d = json.loads(obj_str)
                    except json.JSONDecodeError:
                        continue
                    oid = d.get("id")
                    if oid is not None and oid not in collected:
                        collected[oid] = d
                        new += 1

                if new == 0:  # plus rien de nouveau → fin de pagination
                    break

            log.info("[BJ/freeje] %d pharmacies collectées (%d page(s)).",
                     len(collected), last_page)
            return json.dumps(list(collected.values()))

    # ── parse ──────────────────────────────────────────────────────
    def parse(self, raw: str) -> list[dict]:
        """Mappe chaque objet source vers le contrat BaseScraper (+ GPS + garde)."""
        items = json.loads(raw)
        pharmacies: list[dict] = []

        for it in items:
            name = (it.get("nom") or "").strip()
            city = (it.get("zone") or "").strip().upper()
            if not name or not city:
                continue

            address = (it.get("adresse") or "").strip() or None
            phone   = (it.get("telephone") or "").strip() or None

            pharmacies.append({
                "name":         name,
                "contact_name": None,
                "address":      address,
                "city_name":    city,
                "phone":        phone,
                # Champs enrichis exploités par BaseScraper.sync()
                "latitude":     _to_float(it.get("latitude")),
                "longitude":    _to_float(it.get("longitude")),
                "en_garde":     bool(it.get("en_garde")),
            })

        log.info("[BJ/freeje] %d pharmacies parsées.", len(pharmacies))
        return pharmacies
