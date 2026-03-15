"""
countries.py
============
Endpoints publics pour la liste des pays disponibles dans Pharmaco.

La collection `countries` est alimentée automatiquement par BaseScraper.sync()
à chaque passage du scraper. Un pays apparaît dès qu'un scraper l'a exécuté.
"""

from fastapi import APIRouter, HTTPException
from app.database import get_db

router = APIRouter(prefix="/countries", tags=["Pays"])


@router.get("")
async def list_countries():
    """
    Retourne tous les pays disponibles avec le nombre de villes
    et de pharmacies associées.

    Un pays devient disponible dès que son scraper a été exécuté.
    """
    db = get_db()

    # Lire la collection countries directement
    countries = await db.countries.find().sort("country_name", 1).to_list(length=200)

    # Enrichir avec les comptages depuis cities et pharmacies
    result = []
    for c in countries:
        cc = c["country_code"]
        city_count = await db.cities.count_documents({"country_code": cc})
        city_ids   = await db.cities.distinct("_id", {"country_code": cc})
        pharm_count = await db.pharmacies.count_documents({
            "city_id": {"$in": city_ids},
            "is_active": True,
        })
        result.append({
            "country_code":    cc,
            "country_name":    c["country_name"],
            "city_count":      city_count,
            "pharmacy_count":  pharm_count,
            "last_scraped_at": c.get("last_scraped_at"),
        })

    return result


@router.get("/{country_code}")
async def get_country(country_code: str):
    """
    Détail d'un pays : informations générales + liste des villes
    avec le nombre de pharmacies par ville.
    """
    db = get_db()
    cc = country_code.upper()

    country = await db.countries.find_one({"country_code": cc})
    if not country:
        raise HTTPException(
            status_code=404,
            detail=f"Pays '{cc}' introuvable. Vérifiez que le scraper correspondant a bien été exécuté."
        )

    # Villes du pays avec comptage pharmacies
    pipeline = [
        {"$match": {"country_code": cc}},
        {"$lookup": {
            "from": "pharmacies",
            "let": {"city_id": "$_id"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$city_id", "$$city_id"]}, "is_active": True}}
            ],
            "as": "pharmacies",
        }},
        {"$project": {
            "name": 1,
            "department": 1,
            "pharmacy_count": {"$size": "$pharmacies"},
        }},
        {"$sort": {"name": 1}},
    ]
    cities = await db.cities.aggregate(pipeline).to_list(length=500)

    return {
        "country_code":    cc,
        "country_name":    country["country_name"],
        "last_scraped_at": country.get("last_scraped_at"),
        "city_count":      len(cities),
        "cities": [
            {
                "id":              str(c["_id"]),
                "name":            c["name"],
                "department":      c.get("department"),
                "pharmacy_count":  c["pharmacy_count"],
            }
            for c in cities
        ],
    }
