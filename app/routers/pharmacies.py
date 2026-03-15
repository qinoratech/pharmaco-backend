import re
from fastapi import APIRouter, HTTPException, Query, status, Depends
from bson import ObjectId
from bson.errors import InvalidId
from datetime import date

from app.database import get_db
from app.schemas.pharmacy import PharmacyCreate, PharmacyUpdate, PharmacyOut
from app.core.security import require_admin

router = APIRouter(prefix="/pharmacies", tags=["Pharmacies"])


async def _enrich(doc: dict, db) -> PharmacyOut:
    city_doc = await db.cities.find_one({"_id": doc.get("city_id")})
    city_name = city_doc["name"] if city_doc else None
    country_code = city_doc.get("country_code") if city_doc else None
    country_name = city_doc.get("country_name") if city_doc else None

    today = date.today().isoformat()
    duty = await db.duty_schedules.find_one({
        "pharmacy_id": doc["_id"],
        "date": today,
        "validated": True,
    })

    loc = doc.get("location", {}) or {}
    coords = loc.get("coordinates", [None, None])
    return PharmacyOut(
        id=str(doc["_id"]),
        name=doc["name"],
        contact_name=doc.get("contact_name"),
        address=doc.get("address"),
        phone=doc.get("phone"),
        city_id=str(doc.get("city_id", "")),
        city_name=city_name,
        country_code=country_code,
        country_name=country_name,
        latitude=coords[1],
        longitude=coords[0],
        is_active=doc.get("is_active", True),
        is_on_duty_today=duty is not None,
    )


async def _city_ids_for_filter(db, country_code: str | None, city_name: str | None) -> list | None:
    """Retourne les city ObjectIds matchant les filtres, ou None si pas de filtre."""
    f: dict = {}
    if country_code:
        f["country_code"] = country_code.upper()
    if city_name:
        f["name"] = {"$regex": f"^{city_name}$", "$options": "i"}
    if not f:
        return None
    return await db.cities.distinct("_id", f)


# ── Public ─────────────────────────────────────────────────────────
@router.get("", response_model=list[PharmacyOut])
async def list_pharmacies(
    country_code: str | None = Query(None, description="Ex: BJ"),
    city_id: str | None = Query(None),
    city_name: str | None = Query(None),
    on_duty_today: bool = Query(False),
    search: str | None = Query(None),
    active_only: bool = Query(True),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    db = get_db()
    query: dict = {}
    if active_only:
        query["is_active"] = True

    if city_id:
        try:
            query["city_id"] = ObjectId(city_id)
        except InvalidId:
            raise HTTPException(status_code=400, detail="city_id invalide")
    else:
        city_ids = await _city_ids_for_filter(db, country_code, city_name)
        if city_ids is not None:
            if not city_ids:
                return []
            query["city_id"] = {"$in": city_ids}

    if search:
        pattern = re.escape(search.strip())
        # Exact city name match (case-insensitive) to avoid partial matches between cities
        city_ids_from_search = await db.cities.distinct(
            "_id", {"name": {"$regex": f"^{pattern}$", "$options": "i"}}
        )
        if city_ids_from_search:
            if "city_id" in query:
                existing = query["city_id"].get("$in", [query["city_id"]])
                query["city_id"] = {"$in": list(set(existing) & set(city_ids_from_search))}
            else:
                query["city_id"] = {"$in": city_ids_from_search}
        else:
            # Fall back: partial city match then pharmacy name regex
            city_ids_partial = await db.cities.distinct(
                "_id", {"name": {"$regex": pattern, "$options": "i"}}
            )
            search_conditions: list[dict] = [{"name": {"$regex": pattern, "$options": "i"}}]
            if city_ids_partial:
                search_conditions.append({"city_id": {"$in": city_ids_partial}})
            query["$or"] = search_conditions

    if on_duty_today:
        today = date.today().isoformat()
        duty_ids = await db.duty_schedules.distinct(
            "pharmacy_id", {"date": today, "validated": True}
        )
        if "_id" in query:
            query["_id"]["$in"] = list(set(query["_id"]["$in"]) & set(duty_ids))
        else:
            query["_id"] = {"$in": duty_ids}

    docs = await db.pharmacies.find(query).skip(skip).limit(limit).to_list(length=limit)
    return [await _enrich(d, db) for d in docs]


@router.get("/on-duty-today", response_model=list[PharmacyOut])
async def pharmacies_on_duty_today(
    country_code: str | None = Query(None, description="Ex: BJ"),
    city_id: str | None = Query(None),
    city_name: str | None = Query(None),
    on_duty_today: bool = Query(False),
    search: str | None = Query(None),
    active_only: bool = Query(True),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    db = get_db()
    query: dict = {}
    if active_only:
        query["is_active"] = True

    if city_id:
        try:
            query["city_id"] = ObjectId(city_id)
        except InvalidId:
            raise HTTPException(status_code=400, detail="city_id invalide")
    else:
        city_ids = await _city_ids_for_filter(db, country_code, city_name)
        if city_ids is not None:
            if not city_ids:
                return []
            query["city_id"] = {"$in": city_ids}

    if search:
        pattern = re.escape(search.strip())
        city_ids_from_search = await db.cities.distinct(
            "_id", {"name": {"$regex": f"^{pattern}$", "$options": "i"}}
        )
        if city_ids_from_search:
            if "city_id" in query:
                existing = query["city_id"].get("$in", [query["city_id"]])
                query["city_id"] = {"$in": list(set(existing) & set(city_ids_from_search))}
            else:
                query["city_id"] = {"$in": city_ids_from_search}
        else:
            city_ids_partial = await db.cities.distinct(
                "_id", {"name": {"$regex": pattern, "$options": "i"}}
            )
            search_conditions: list[dict] = [{"name": {"$regex": pattern, "$options": "i"}}]
            if city_ids_partial:
                search_conditions.append({"city_id": {"$in": city_ids_partial}})
            query["$or"] = search_conditions

    if on_duty_today:
        today = date.today().isoformat()
        duty_ids = await db.duty_schedules.distinct(
            "pharmacy_id", {"date": today, "validated": True}
        )
        if "_id" in query:
            query["_id"]["$in"] = list(set(query["_id"]["$in"]) & set(duty_ids))
        else:
            query["_id"] = {"$in": duty_ids}

    docs = await db.pharmacies.find(query).skip(skip).limit(limit).to_list(length=limit)
    return [await _enrich(d, db) for d in docs]

@router.get("/nearby", response_model=list[PharmacyOut])
async def pharmacies_nearby(
    latitude: float = Query(...),
    longitude: float = Query(...),
    radius_km: float = Query(5.0, ge=0.1, le=100.0),
    on_duty_today: bool = Query(False),
    country_code: str | None = Query(None),
):
    """Pharmacies dans un rayon donné, filtrables par pays."""
    db = get_db()
    query: dict = {
        "is_active": True,
        "location": {
            "$near": {
                "$geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                "$maxDistance": int(radius_km * 1000),
            }
        },
    }
    if country_code:
        city_ids = await db.cities.distinct("_id", {"country_code": country_code.upper()})
        query["city_id"] = {"$in": city_ids}

    if on_duty_today:
        today = date.today().isoformat()
        duty_ids = await db.duty_schedules.distinct(
            "pharmacy_id", {"date": today, "validated": True}
        )
        query["_id"] = {"$in": duty_ids}

    docs = await db.pharmacies.find(query).limit(20).to_list(length=20)
    return [await _enrich(d, db) for d in docs]


@router.get("/{pharmacy_id}", response_model=PharmacyOut)
async def get_pharmacy(pharmacy_id: str):
    db = get_db()
    try:
        doc = await db.pharmacies.find_one({"_id": ObjectId(pharmacy_id)})
    except InvalidId:
        raise HTTPException(status_code=400, detail="ID invalide")
    if not doc:
        raise HTTPException(status_code=404, detail="Pharmacie introuvable")
    return await _enrich(doc, db)


# ── Admin ──────────────────────────────────────────────────────────
@router.post("", response_model=PharmacyOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_admin)])
async def create_pharmacy(payload: PharmacyCreate):
    db = get_db()
    try:
        city_oid = ObjectId(payload.city_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="city_id invalide")
    if not await db.cities.find_one({"_id": city_oid}):
        raise HTTPException(status_code=404, detail="Ville introuvable")

    data = payload.model_dump(exclude={"city_id", "latitude", "longitude"})
    data["city_id"] = city_oid

    if payload.latitude is not None and payload.longitude is not None:
        data["location"] = {
            "type": "Point",
            "coordinates": [payload.longitude, payload.latitude],
        }

    result = await db.pharmacies.insert_one(data)
    doc = await db.pharmacies.find_one({"_id": result.inserted_id})
    return await _enrich(doc, db)


@router.patch("/{pharmacy_id}", response_model=PharmacyOut,
              dependencies=[Depends(require_admin)])
async def update_pharmacy(pharmacy_id: str, payload: PharmacyUpdate):
    db = get_db()
    try:
        oid = ObjectId(pharmacy_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="ID invalide")

    update_data = {k: v for k, v in payload.model_dump().items() if v is not None}

    if "city_id" in update_data:
        try:
            update_data["city_id"] = ObjectId(update_data["city_id"])
        except InvalidId:
            raise HTTPException(status_code=400, detail="city_id invalide")

    lat = update_data.pop("latitude", None)
    lon = update_data.pop("longitude", None)
    if lat is not None and lon is not None:
        update_data["location"] = {"type": "Point", "coordinates": [lon, lat]}

    if not update_data:
        raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")

    result = await db.pharmacies.update_one({"_id": oid}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Pharmacie introuvable")
    doc = await db.pharmacies.find_one({"_id": oid})
    return await _enrich(doc, db)


@router.delete("/{pharmacy_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_admin)])
async def delete_pharmacy(pharmacy_id: str):
    db = get_db()
    try:
        oid = ObjectId(pharmacy_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="ID invalide")
    result = await db.pharmacies.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Pharmacie introuvable")
