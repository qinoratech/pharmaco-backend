"""
Sources de données par pays.

Pour ajouter un nouveau pays :
─────────────────────────────
1. Créer un fichier  app/worker/sources/<cc>_<nom>.py
   ex: tg_monpharmacien.py  (cc = code ISO du pays)
2. Étendre BaseScraper, définir country_code, country_name,
   source_url, source_name
3. Implémenter fetch() et parse()
4. Décorer la classe avec @register_scraper
5. C'est tout — le ScraperManager la détectera automatiquement.

Exemple minimal :
─────────────────
    from app.worker.base_scraper import BaseScraper
    from app.worker.scraper_registry import register_scraper
    import httpx

    @register_scraper
    class TogoScraper(BaseScraper):
        country_code = "TG"
        country_name = "Togo"
        source_url   = "https://monpharmacien.tg/liste"
        source_name  = "monpharmacien"

        async def fetch(self) -> str:
            async with httpx.AsyncClient() as c:
                return (await c.get(self.source_url)).text

        def parse(self, raw: str) -> list[dict]:
            # ... parser spécifique à la source
            return [{"name": "...", "city_name": "LOMÉ", "phone": "..."}]
"""
