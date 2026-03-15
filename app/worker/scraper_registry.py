"""
scraper_registry.py
===================
Registre central de tous les scrapers actifs.

Usage :
    from app.worker.scraper_registry import register_scraper, get_all_scrapers

    @register_scraper
    class MyNewScraper(BaseScraper):
        country_code = "TG"
        ...

Le ScraperManager appelle get_all_scrapers() pour découvrir
automatiquement tous les scrapers enregistrés.
"""

from __future__ import annotations
import importlib
import pkgutil
import logging
from typing import Type
from app.worker.base_scraper import BaseScraper

log = logging.getLogger("pharmaco.registry")

_REGISTRY: dict[str, Type[BaseScraper]] = {}


def register_scraper(cls: Type[BaseScraper]) -> Type[BaseScraper]:
    """Décorateur — enregistre un scraper dans le registre global."""
    key = f"{cls.country_code}:{cls.source_name}"
    if key in _REGISTRY:
        log.warning("Scraper déjà enregistré pour la clé '%s', écrasement.", key)
    _REGISTRY[key] = cls
    log.debug("Scraper enregistré : %s (%s)", cls.__name__, key)
    return cls


def get_all_scrapers() -> list[BaseScraper]:
    """
    Instancie et retourne tous les scrapers enregistrés.
    Charge automatiquement tous les modules dans app/worker/sources/.
    """
    _autodiscover()
    return [cls() for cls in _REGISTRY.values()]


def _autodiscover() -> None:
    """
    Parcourt le package app.worker.sources et importe chaque module.
    L'import déclenche le décorateur @register_scraper.
    """
    try:
        import app.worker.sources as sources_pkg
        pkg_path = sources_pkg.__path__
        for _, module_name, _ in pkgutil.iter_modules(pkg_path):
            full_name = f"app.worker.sources.{module_name}"
            try:
                importlib.import_module(full_name)
            except Exception as exc:
                log.error("Impossible de charger le module scraper '%s' : %s", full_name, exc)
    except Exception as exc:
        log.error("Autodiscovery échouée : %s", exc)
