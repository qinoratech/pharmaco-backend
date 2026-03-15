import re
from fastapi import APIRouter, HTTPException, Query, status, Depends
from bson import ObjectId
from bson.errors import InvalidId
from datetime import date

from app.database import get_db
from app.schemas.duty import DutyCreate, DutyUpdate, DutyOut
from app.core.security import require_admin

router = APIRouter(prefix="/duties", tags=["Gardes"])


async def _resolve_pharmacy_ids(db, country_code: str | None, city_name: str | None) -> list | None:
    """Returns pharmacy ObjectIds matching country/city filters, or None if no filter."""
    if not country_code and not city_name:
        return None

    city_filter: dict = {}
    if country_code:
        city_filter["country_code"] = country_code.upper()

    if city_name:
        pattern = re.escape(city_name.strip())
        # Exact match first, fallback to partial if no result
        city_ids = await db.cities.distinct("_id", {**city_filter, "name": {"$regex": f"^{pattern}$", "$options": "i"}})
        if not city_ids:
            city_ids = await db.cities.distinct("_id", {**city_filter, "name": {"$regex": pattern, "$options": "i"}})
    else:
        city_ids = await db.cities.distinct("_id", city_filter)

    if not city_ids:
        return []

    return await db.pharmacies.distinct("_id", {"city_id": {"$in": city_ids}})


async def _enrich(doc: dict, db) -> DutyOut:
    pharmacy = await db.pharmacies.find_one({"_id": doc["pharmacy_id"]})
    city, country_code, country_name = None, None, None
    if pharmacy:
        city = await db.cities.find_one({"_id": pharmacy.get("city_id")})
        if city:
            country_code = city.get("country_code")
            country_name = city.get("country_name")
    return DutyOut(
        id=str(doc["_id"]),
        pharmacy_id=str(doc["pharmacy_id"]),
        pharmacy_name=pharmacy["name"] if pharmacy else None,
        city_name=city["name"] if city else None,
        country_code=country_code,
        country_name=country_name,
        phone=pharmacy.get("phone") if pharmacy else None,
        address=pharmacy.get("address") if pharmacy else None,
        date=date.fromisoformat(doc["date"]),
        validated=doc.get("validated", False),
    )


# ── Public ─────────────────────────────────────────────────────────
@router.get("", response_model=list[DutyOut])
async def list_duties(
    city_name: str | None = Query(None),
    country_code: str | None = Query(None, description="Ex: BJ"),
    validated_only: bool = Query(True),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """Liste les gardes, filtrables par ville et/ou pays."""
    db = get_db()
    query: dict = {}

    if validated_only:
        query["validated"] = True

    pharmacy_ids = await _resolve_pharmacy_ids(db, country_code, city_name)
    if pharmacy_ids is not None:
        if not pharmacy_ids:
            return []
        query["pharmacy_id"] = {"$in": pharmacy_ids}

    docs = await db.duty_schedules.find(query).skip(skip).limit(limit).to_list(length=limit)
    return [await _enrich(d, db) for d in docs]


@router.get("/today", response_model=list[DutyOut])
async def duties_today(
    city_name: str | None = Query(None),
    country_code: str | None = Query(None, description="Ex: BJ"),
):
    """Gardes actives aujourd'hui, filtrables par ville et/ou pays."""
    today = date.today().isoformat()
    db = get_db()
    query: dict = {"date": today, "validated": True}

    pharmacy_ids = await _resolve_pharmacy_ids(db, country_code, city_name)
    if pharmacy_ids is not None:
        if not pharmacy_ids:
            return []
        query["pharmacy_id"] = {"$in": pharmacy_ids}

    docs = await db.duty_schedules.find(query).to_list(length=200)
    return [await _enrich(d, db) for d in docs]


@router.get("/{duty_id}", response_model=DutyOut)
async def get_duty(duty_id: str):
    db = get_db()
    try:
        doc = await db.duty_schedules.find_one({"_id": ObjectId(duty_id)})
    except InvalidId:
        raise HTTPException(status_code=400, detail="ID invalide")
    if not doc:
        raise HTTPException(status_code=404, detail="Garde introuvable")
    return await _enrich(doc, db)


# ── Admin ──────────────────────────────────────────────────────────
@router.post("", response_model=DutyOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_admin)])
async def create_duty(payload: DutyCreate):
    db = get_db()
    try:
        pharm_oid = ObjectId(payload.pharmacy_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="pharmacy_id invalide")
    if not await db.pharmacies.find_one({"_id": pharm_oid}):
        raise HTTPException(status_code=404, detail="Pharmacie introuvable")

    # Éviter les doublons (même pharmacie, même jour)
    existing = await db.duty_schedules.find_one({
        "pharmacy_id": pharm_oid,
        "date": payload.date.isoformat(),
    })
    if existing:
        raise HTTPException(status_code=409, detail="Une garde existe déjà pour cette pharmacie ce jour-là")

    data = {
        "pharmacy_id": pharm_oid,
        "date": payload.date.isoformat(),
        "validated": payload.validated,
    }
    result = await db.duty_schedules.insert_one(data)
    doc = await db.duty_schedules.find_one({"_id": result.inserted_id})
    return await _enrich(doc, db)


@router.patch("/{duty_id}", response_model=DutyOut, dependencies=[Depends(require_admin)])
async def update_duty(duty_id: str, payload: DutyUpdate):
    db = get_db()
    try:
        oid = ObjectId(duty_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="ID invalide")

    update_data = {}
    if payload.date is not None:
        update_data["date"] = payload.date.isoformat()
    if payload.validated is not None:
        update_data["validated"] = payload.validated

    if not update_data:
        raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")

    result = await db.duty_schedules.update_one({"_id": oid}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Garde introuvable")
    doc = await db.duty_schedules.find_one({"_id": oid})
    return await _enrich(doc, db)


@router.patch("/{duty_id}/validate", response_model=DutyOut,
              dependencies=[Depends(require_admin)])
async def validate_duty(duty_id: str):
    """Valider officiellement une garde."""
    db = get_db()
    try:
        oid = ObjectId(duty_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="ID invalide")
    result = await db.duty_schedules.update_one({"_id": oid}, {"$set": {"validated": True}})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Garde introuvable")
    doc = await db.duty_schedules.find_one({"_id": oid})
    return await _enrich(doc, db)


@router.delete("/{duty_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_admin)])
async def delete_duty(duty_id: str):
    db = get_db()
    try:
        oid = ObjectId(duty_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="ID invalide")
    result = await db.duty_schedules.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Garde introuvable")
