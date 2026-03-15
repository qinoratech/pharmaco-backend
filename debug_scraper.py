#!/usr/bin/env python3
"""
debug_scraper.py
================
Script de diagnostic — teste chaque étape indépendamment.
Lance ce script EN PREMIER si le seed.py ne fonctionne pas.

Usage :  python debug_scraper.py
"""

import asyncio
import sys
import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("debug")

SEP = "─" * 60


async def test_mongo() -> bool:
    print(f"\n{SEP}")
    print("ÉTAPE 1 : Connexion MongoDB")
    print(SEP)
    try:
        from app.config import get_settings
        from app.database import connect_db, get_db, close_db
        settings = get_settings()
        log.info("MONGO_URI = %s", settings.MONGO_URI)
        log.info("MONGO_DB  = %s", settings.MONGO_DB)
        await connect_db()
        db = get_db()
        collections = await db.list_collection_names()
        log.info("✅ Connecté — collections existantes : %s", collections or "(aucune)")
        await close_db()
        return True
    except Exception as e:
        log.error("❌ ÉCHEC connexion MongoDB : %s", e)
        log.error("→ Vérifiez que MongoDB tourne et que MONGO_URI est correct dans .env")
        return False


async def test_fetch() -> str | None:
    print(f"\n{SEP}")
    print("ÉTAPE 2 : Téléchargement ubphar.com")
    print(SEP)
    try:
        from app.worker.sources.bj_ubphar import UbpharBeninScraper
        scraper = UbpharBeninScraper()
        log.info("URL : %s", scraper.source_url)
        html = await scraper.fetch()
        log.info("✅ Téléchargé — taille : %d octets", len(html))
        # Aperçu
        snippet = html[:300].replace("\n", " ")
        log.info("Aperçu HTML : %s…", snippet)
        return html
    except Exception as e:
        log.error("❌ ÉCHEC téléchargement : %s", e)
        log.error("→ Vérifiez votre connexion internet et que ubphar.com est accessible")
        return None


def test_parse(html: str) -> list | None:
    print(f"\n{SEP}")
    print("ÉTAPE 3 : Parsing HTML")
    print(SEP)
    try:
        from app.worker.sources.bj_ubphar import UbpharBeninScraper
        scraper = UbpharBeninScraper()
        pharmacies = scraper.parse(html)
        log.info("✅ %d pharmacies parsées", len(pharmacies))
        if pharmacies:
            log.info("Premier résultat : %s", pharmacies[0])
            log.info("Dernier résultat : %s", pharmacies[-1])
        else:
            log.warning("⚠ Liste vide — la structure HTML a peut-être changé")
        return pharmacies
    except Exception as e:
        log.error("❌ ÉCHEC parsing : %s", e)
        import traceback; traceback.print_exc()
        return None


async def test_sync(pharmacies: list) -> bool:
    print(f"\n{SEP}")
    print("ÉTAPE 4 : Insertion MongoDB")
    print(SEP)
    try:
        from app.database import connect_db, get_db, close_db, create_indexes
        from app.worker.sources.bj_ubphar import UbpharBeninScraper

        await connect_db()
        await create_indexes()
        db = get_db()
        scraper = UbpharBeninScraper()

        # Test avec seulement les 5 premières pharmacies
        sample = pharmacies[:5]
        log.info("Test avec %d pharmacies…", len(sample))
        stats = await scraper.sync(db, sample)
        log.info("✅ Sync OK : %s", stats)

        # Vérification
        n = await db.pharmacies.count_documents({})
        nc = await db.countries.count_documents({})
        nv = await db.cities.count_documents({})
        log.info("Base après insertion — countries: %d | cities: %d | pharmacies: %d", nc, nv, n)

        await close_db()
        return True
    except Exception as e:
        log.error("❌ ÉCHEC insertion : %s", e)
        import traceback; traceback.print_exc()
        return False


async def main():
    print("\n" + "═" * 60)
    print("  PHARMACO — Diagnostic Scraper")
    print("═" * 60)

    # Étape 1 : MongoDB
    mongo_ok = await test_mongo()
    if not mongo_ok:
        print("\n❌ Arrêt : MongoDB inaccessible.")
        sys.exit(1)

    # Étape 2 : Fetch
    html = await test_fetch()
    if html is None:
        print("\n❌ Arrêt : impossible de télécharger la source.")
        sys.exit(1)

    # Étape 3 : Parse
    pharmacies = test_parse(html)
    if not pharmacies:
        print("\n❌ Arrêt : parsing retourne zéro résultat.")
        sys.exit(1)

    # Étape 4 : Sync
    sync_ok = await test_sync(pharmacies)

    print(f"\n{'═' * 60}")
    if sync_ok:
        print("✅  Tous les tests passent — vous pouvez lancer seed.py")
    else:
        print("❌  Échec à l'étape d'insertion — voir les erreurs ci-dessus")
    print("═" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
