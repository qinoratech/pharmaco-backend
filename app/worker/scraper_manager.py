"""
scraper_manager.py
==================
Point d'entrée du worker Supervisord.

Lance tous les scrapers actifs en séquence, puis attend
SCRAPER_INTERVAL_HOURS heures avant de recommencer.

─── Ajouter un nouveau pays ───────────────────────────────────────
1. Créer app/worker/sources/<cc>_<source>.py  (voir bj_ubphar.py)
2. Ajouter une ligne d'import dans la section SOURCES ci-dessous
3. Redémarrer supervisord — c'est tout.
───────────────────────────────────────────────────────────────────

Lancé par Supervisord :
    command=python scraper_manager.py
    directory=%(here)s/app/worker
"""

import asyncio
import logging
import sys
import traceback
from pathlib import Path

# ── Résolution du chemin racine ────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]   # qinora/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pharmaco.manager")

# ══════════════════════════════════════════════════════════════════
# SOURCES — importer chaque scraper ici (un import = un pays)
# ══════════════════════════════════════════════════════════════════
from app.worker.sources.bj_ubphar import UbpharBeninScraper
# from app.worker.sources.tg_monpharmacien import TogoScraper  ← exemple futur

SCRAPERS = [
    UbpharBeninScraper(),
    # TogoScraper(),
]
# ══════════════════════════════════════════════════════════════════


async def run_all_once() -> None:
    """Exécute tous les scrapers en séquence avec gestion explicite des erreurs."""
    from app.config import get_settings
    from app.database import get_client

    settings = get_settings()
    db = get_client()[settings.MONGO_DB]

    log.info("=== Pharmaco ScraperManager — %d scraper(s) actif(s) ===", len(SCRAPERS))

    ok = 0
    ko = 0
    for scraper in SCRAPERS:
        log.info("→ [%s] %s …", scraper.country_code, scraper.source_name)
        try:
            await scraper.run(db)
            ok += 1
        except Exception:
            ko += 1
            log.error(
                "✗ Scraper [%s:%s] a échoué :\n%s",
                scraper.country_code,
                scraper.source_name,
                traceback.format_exc(),
            )

    log.info("=== Terminé — succès: %d | échecs: %d ===", ok, ko)


async def main_loop() -> None:
    from app.config import get_settings
    settings = get_settings()

    interval = settings.SCRAPER_INTERVAL_HOURS * 3600
    while True:
        await run_all_once()
        log.info("Prochain cycle dans %d heure(s).", settings.SCRAPER_INTERVAL_HOURS)
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(main_loop())
