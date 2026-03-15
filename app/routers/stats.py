"""
stats.py
========
Endpoints de statistiques publics (KPIs du cahier des charges).

GET /api/v1/stats          → vue globale
GET /api/v1/stats/scraper  → état des derniers scraping par pays (admin)
"""

from fastapi import APIRouter, Depends
from datetime import date, datetime, timezone

from app.database import get_db
from app.core.security import require_admin

router = APIRouter(prefix="/stats", tags=["Statistiques"])


# ── Public ─────────────────────────────────────────────────────────
@router.get("")
async def global_stats():
    """
    KPIs publics :
    - Nombre de pharmacies enregistrées
    - Nombre de villes couvertes
    - Nombre de pays couverts
    - Nombre de gardes validées aujourd'hui
    - Nombre de gardes validées ce mois-ci
    """
    db = get_db()
    today = date.today().isoformat()
    month_start = date.today().replace(day=1).isoformat()

    # Comptages parallèles
    total_pharmacies   = await db.pharmacies.count_documents({"is_active": True})
    total_cities       = await db.cities.count_documents({})
    duties_today       = await db.pharmacies.count_documents({"is_active": True})
    duties_this_month  = await db.duty_schedules.count_documents({
        "date": {"$gte": month_start},
        "validated": True,
    })

    # Pays distincts
    countries = await db.cities.distinct("country_code")
    countries = [c for c in countries if c]

    # Villes avec au moins une pharmacie
    cities_with_pharmacy = await db.pharmacies.distinct("city_id", {"is_active": True})

    # Répartition par pays
    pipeline = [
        {"$match": {"is_active": True}},
        {"$lookup": {
            "from": "cities",
            "localField": "city_id",
            "foreignField": "_id",
            "as": "city",
        }},
        {"$unwind": {"path": "$city", "preserveNullAndEmptyArrays": True}},
        {"$group": {
            "_id": "$city.country_code",
            "country_name": {"$first": "$city.country_name"},
            "pharmacy_count": {"$sum": 1},
        }},
        {"$sort": {"pharmacy_count": -1}},
    ]
    by_country = await db.pharmacies.aggregate(pipeline).to_list(length=100)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pharmacies": {
            "total": total_pharmacies,
            "cities_covered": len(cities_with_pharmacy),
            "countries_covered": len(countries),
            "by_country": [
                {
                    "country_code": r["_id"] or "??",
                    "country_name": r.get("country_name") or "Inconnu",
                    "count": r["pharmacy_count"],
                }
                for r in by_country
            ],
        },
        "duties": {
            "today": duties_today,
            "this_month": duties_this_month,
        },
        "coverage": {
            "total_cities": total_cities,
            "countries": countries,
        },
    }


# ── Admin ──────────────────────────────────────────────────────────
@router.get("/scraper", dependencies=[Depends(require_admin)])
async def scraper_status():
    """
    État des derniers scraping pour chaque source.
    Affiche la date du dernier passage et le nombre de pharmacies
    synchronisées par source.
    """
    db = get_db()
    pipeline = [
        {"$match": {"source": {"$exists": True, "$ne": None}}},
        {"$group": {
            "_id": "$source",
            "count": {"$sum": 1},
            "last_scraped_at": {"$max": "$last_scraped_at"},
        }},
        {"$sort": {"_id": 1}},
    ]
    sources = await db.pharmacies.aggregate(pipeline).to_list(length=50)

    return {
        "sources": [
            {
                "source": r["_id"],
                "pharmacy_count": r["count"],
                "last_scraped_at": r.get("last_scraped_at"),
            }
            for r in sources
        ]
    }


@router.get("/duties/pending", dependencies=[Depends(require_admin)])
async def pending_duties():
    """Gardes non encore validées, en attente de validation admin."""
    db = get_db()
    pipeline = [
        {"$match": {"validated": False}},
        {"$lookup": {
            "from": "pharmacies",
            "localField": "pharmacy_id",
            "foreignField": "_id",
            "as": "pharmacy",
        }},
        {"$unwind": {"path": "$pharmacy", "preserveNullAndEmptyArrays": True}},
        {"$lookup": {
            "from": "cities",
            "localField": "pharmacy.city_id",
            "foreignField": "_id",
            "as": "city",
        }},
        {"$unwind": {"path": "$city", "preserveNullAndEmptyArrays": True}},
        {"$project": {
            "date": 1,
            "pharmacy_name": "$pharmacy.name",
            "city_name": "$city.name",
            "country_code": "$city.country_code",
        }},
        {"$sort": {"date": 1}},
        {"$limit": 100},
    ]
    docs = await db.duty_schedules.aggregate(pipeline).to_list(length=100)
    return [
        {
            "id": str(d["_id"]),
            "date": d.get("date"),
            "pharmacy_name": d.get("pharmacy_name"),
            "city_name": d.get("city_name"),
            "country_code": d.get("country_code"),
        }
        for d in docs
    ]
