from fastapi import APIRouter, HTTPException, Query, status, Depends
from bson import ObjectId
from bson.errors import InvalidId

from app.database import get_db
from app.schemas.city import CityCreate, CityUpdate, CityOut
from app.core.security import require_admin

router = APIRouter(prefix="/cities", tags=["Villes"])


def _city_to_out(doc: dict) -> CityOut:
    return CityOut(
        id=str(doc["_id"]),
        name=doc["name"],
        department=doc.get("department"),
        country_code=doc.get("country_code", ""),
        country_name=doc.get("country_name", ""),
    )


# ── Public ─────────────────────────────────────────────────────────
@router.get("", response_model=list[CityOut])
async def list_cities(
    country_code: str | None = Query(None, description="Filtrer par pays, ex: BJ"),
):
    """Retourne toutes les villes, filtrables par pays."""
    db = get_db()
    query: dict = {}
    if country_code:
        query["country_code"] = country_code.upper()
    docs = await db.cities.find(query).sort("name", 1).to_list(length=500)
    return [_city_to_out(d) for d in docs]


@router.get("/countries", tags=["Pays"])
async def list_countries():
    """Retourne la liste des pays disponibles dans la base."""
    db = get_db()
    pipeline = [
        {"$group": {"_id": "$country_code", "country_name": {"$first": "$country_name"}, "city_count": {"$sum": 1}}},
        {"$sort": {"country_name": 1}},
    ]
    results = await db.cities.aggregate(pipeline).to_list(length=100)
    return [
        {"country_code": r["_id"], "country_name": r["country_name"], "city_count": r["city_count"]}
        for r in results if r["_id"]
    ]


@router.get("/{city_id}", response_model=CityOut)
async def get_city(city_id: str):
    db = get_db()
    try:
        doc = await db.cities.find_one({"_id": ObjectId(city_id)})
    except InvalidId:
        raise HTTPException(status_code=400, detail="ID invalide")
    if not doc:
        raise HTTPException(status_code=404, detail="Ville introuvable")
    return _city_to_out(doc)


# ── Admin ──────────────────────────────────────────────────────────
@router.post("", response_model=CityOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_admin)])
async def create_city(payload: CityCreate):
    db = get_db()
    existing = await db.cities.find_one({
        "name": {"$regex": f"^{payload.name}$", "$options": "i"},
        "country_code": payload.country_code.upper(),
    })
    if existing:
        raise HTTPException(status_code=409, detail="Ville déjà existante pour ce pays")
    data = payload.model_dump()
    data["country_code"] = data["country_code"].upper()
    result = await db.cities.insert_one(data)
    doc = await db.cities.find_one({"_id": result.inserted_id})
    return _city_to_out(doc)


@router.patch("/{city_id}", response_model=CityOut, dependencies=[Depends(require_admin)])
async def update_city(city_id: str, payload: CityUpdate):
    db = get_db()
    try:
        oid = ObjectId(city_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="ID invalide")
    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "country_code" in update_data:
        update_data["country_code"] = update_data["country_code"].upper()
    if not update_data:
        raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
    result = await db.cities.update_one({"_id": oid}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Ville introuvable")
    doc = await db.cities.find_one({"_id": oid})
    return _city_to_out(doc)


@router.delete("/{city_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_admin)])
async def delete_city(city_id: str):
    db = get_db()
    try:
        oid = ObjectId(city_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="ID invalide")
    result = await db.cities.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Ville introuvable")
