#!/usr/bin/env python3
"""
seed.py
=======
Peuple la base de données Pharmaco au premier démarrage.
Appelle directement chaque scraper sans passer par le registry.

Usage :  python seed.py
"""

import asyncio
import logging
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
log = logging.getLogger("pharmaco.seed")


async def main() -> None:
    from app.config import get_settings
    from app.database import connect_db, create_indexes, close_db, get_db

    # ── imports directs des scrapers ──────────────────────────────
    from app.worker.sources.bj_ubphar import UbpharBeninScraper
    # from app.worker.sources.tg_monpharmacien import TogoScraper  ← futur

    scrapers = [
        UbpharBeninScraper(),
        # TogoScraper(),
    ]

    settings = get_settings()

    # ── Connexion ─────────────────────────────────────────────────
    log.info("🔌  Connexion à MongoDB : %s / db=%s", settings.MONGO_URI, settings.MONGO_DB)
    await connect_db()
    log.info("✅  Connecté")

    log.info("📐  Création des index…")
    await create_indexes()
    log.info("✅  Index OK")

    db = get_db()

    # ── Scraping ──────────────────────────────────────────────────
    for scraper in scrapers:
        log.info("🌍  Scraping [%s] depuis %s …", scraper.country_code, scraper.source_url)
        try:
            await scraper.run(db)
            log.info("✅  [%s] terminé avec succès", scraper.country_code)
        except Exception:
            log.error("❌  [%s] ÉCHEC :\n%s", scraper.country_code, traceback.format_exc())

    # ── Résumé ────────────────────────────────────────────────────
    n_countries  = await db.countries.count_documents({})
    n_cities     = await db.cities.count_documents({})
    n_pharmacies = await db.pharmacies.count_documents({})

    log.info("─" * 50)
    log.info("📊  Résumé base de données :")
    log.info("    countries  : %d", n_countries)
    log.info("    cities     : %d", n_cities)
    log.info("    pharmacies : %d", n_pharmacies)
    log.info("─" * 50)

    await close_db()

    if n_pharmacies == 0:
        log.warning("⚠  Aucune pharmacie insérée — vérifier les logs ci-dessus.")
        sys.exit(1)
    else:
        log.info("🎉  Seed terminé — base prête.")


if __name__ == "__main__":
    asyncio.run(main())
