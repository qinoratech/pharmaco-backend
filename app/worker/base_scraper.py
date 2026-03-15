"""
base_scraper.py
===============
Classe de base abstraite que tout scraper de pays doit étendre.

Pour ajouter un nouveau pays :
1. Créer un fichier dans app/worker/sources/  (ex: tg_monpharmacien.py)
2. Étendre BaseScraper
3. Implémenter fetch() et parse()
4. Le décorer avec @register_scraper
→ Le ScraperManager le détecte et le lance automatiquement.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

log = logging.getLogger("pharmaco.scraper")


class BaseScraper(ABC):
    """
    Contrat que chaque scraper source doit respecter.

    Attributs de classe à définir dans chaque sous-classe :
        country_code (str)  : code ISO 3166-1 alpha-2, ex: "BJ", "TG", "SN"
        country_name (str)  : nom lisible,              ex: "Bénin", "Togo"
        source_url   (str)  : URL de la source de données
        source_name  (str)  : identifiant court,        ex: "ubphar", "monpharmacien"
    """

    country_code: str = ""
    country_name: str = ""
    source_url: str = ""
    source_name: str = ""

    # ── Interface obligatoire ──────────────────────────────────────
    @abstractmethod
    async def fetch(self) -> str:
        """Télécharge et retourne le contenu brut (HTML, JSON…) de la source."""
        ...

    @abstractmethod
    def parse(self, raw: str) -> list[dict[str, Any]]:
        """
        Parse le contenu brut et retourne une liste de dicts pharmacie :
        {
            name          : str   (obligatoire)
            contact_name  : str | None
            address       : str | None
            city_name     : str   (obligatoire, en majuscules)
            phone         : str | None
        }
        """
        ...

    # ── Synchronisation MongoDB (commune à tous les scrapers) ──────
    async def sync(self, db: AsyncIOMotorDatabase, pharmacies: list[dict]) -> dict[str, int]:
        """
        Upsert dans l'ordre :
          1. countries  — collection dédiée (un document par pays)
          2. cities     — une par (name, country_code)
          3. pharmacies — une par (name, city_id)

        Retourne {"cities": N, "upserted": N, "updated": N}.
        """
        scraped_at = datetime.now(timezone.utc).isoformat()

        # -- 1. Pays --------------------------------------------------
        await db.countries.update_one(
            {"country_code": self.country_code},
            {
                "$set": {
                    "country_name": self.country_name,
                    "last_scraped_at": scraped_at,
                },
                "$setOnInsert": {
                    "country_code": self.country_code,
                    "created_at": scraped_at,
                },
            },
            upsert=True,
        )
        log.debug("[%s] Pays upsert OK", self.country_code)

        # -- 2. Villes ------------------------------------------------
        city_cache: dict[str, Any] = {}
        for p in pharmacies:
            city_name = p["city_name"]
            if city_name in city_cache:
                continue
            result = await db.cities.find_one_and_update(
                {"name": city_name, "country_code": self.country_code},
                {
                    "$setOnInsert": {
                        "name":         city_name,
                        "country_code": self.country_code,
                        "country_name": self.country_name,
                        "department":   None,
                    }
                },
                upsert=True,
                return_document=True,
            )
            city_cache[city_name] = result["_id"]
        log.debug("[%s] %d ville(s) synchronisée(s)", self.country_code, len(city_cache))

        # -- 3. Pharmacies --------------------------------------------
        upserted = updated = 0
        for p in pharmacies:
            city_oid = city_cache[p["city_name"]]
            result = await db.pharmacies.update_one(
                {"name": p["name"], "city_id": city_oid},
                {
                    "$set": {
                        "contact_name":    p.get("contact_name"),
                        "address":         p.get("address"),
                        "phone":           p.get("phone"),
                        "is_active":       True,
                        "source":          self.source_name,
                        "last_scraped_at": scraped_at,
                    },
                    "$setOnInsert": {
                        "name":     p["name"],
                        "city_id":  city_oid,
                        "location": None,
                    },
                },
                upsert=True,
            )
            if result.upserted_id:
                upserted += 1
            elif result.modified_count:
                updated += 1

        return {"cities": len(city_cache), "upserted": upserted, "updated": updated}

    # ── Cycle complet (fetch → parse → sync) ──────────────────────
    async def run(self, db: AsyncIOMotorDatabase) -> None:
        log.info("[%s] Scraping démarré — source: %s", self.country_code, self.source_url)

        raw = await self.fetch()
        log.info("[%s] Page téléchargée (%d octets)", self.country_code, len(raw))

        pharmacies = self.parse(raw)
        if not pharmacies:
            log.warning("[%s] ⚠ Aucune pharmacie parsée — vérifier le format de la source.", self.country_code)
            return

        log.info("[%s] %d pharmacies parsées, synchronisation…", self.country_code, len(pharmacies))
        stats = await self.sync(db, pharmacies)
        log.info(
            "[%s] ✓ Sync OK — pays: 1 | villes: %d | créées: %d | mises à jour: %d",
            self.country_code, stats["cities"], stats["upserted"], stats["updated"],
        )