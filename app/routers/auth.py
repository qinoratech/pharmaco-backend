from fastapi import APIRouter, HTTPException, status, Depends
from bson import ObjectId

from app.database import get_db
from app.schemas.user import UserCreate, UserLogin, UserOut, Token
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    require_admin,
)

router = APIRouter(prefix="/auth", tags=["Auth"])


def _user_to_out(doc: dict) -> UserOut:
    return UserOut(id=str(doc["_id"]), email=doc["email"], role=doc["role"])


@router.post("/login", response_model=Token)
async def login(payload: UserLogin):
    db = get_db()
    user = await db.users.find_one({"email": payload.email})
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou mot de passe incorrect",
        )
    token = create_access_token({"sub": str(user["_id"])})
    return Token(access_token=token)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, _=Depends(require_admin)):
    """Créer un nouvel admin (réservé aux superadmin / admins existants)."""
    db = get_db()
    if await db.users.find_one({"email": payload.email}):
        raise HTTPException(status_code=409, detail="Email déjà utilisé")
    data = {
        "email": payload.email,
        "password_hash": hash_password(payload.password),
        "role": payload.role,
    }
    result = await db.users.insert_one(data)
    doc = await db.users.find_one({"_id": result.inserted_id})
    return _user_to_out(doc)


@router.post("/bootstrap", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def bootstrap_superadmin(payload: UserCreate):
    """
    Crée le tout premier superadmin si aucun utilisateur n'existe.
    À désactiver en production après la première utilisation.
    """
    db = get_db()
    if await db.users.count_documents({}) > 0:
        raise HTTPException(
            status_code=403,
            detail="Bootstrap désactivé : des utilisateurs existent déjà",
        )
    data = {
        "email": payload.email,
        "password_hash": hash_password(payload.password),
        "role": "superadmin",
    }
    result = await db.users.insert_one(data)
    doc = await db.users.find_one({"_id": result.inserted_id})
    return _user_to_out(doc)


@router.get("/me", response_model=UserOut)
async def me(current_user=Depends(get_current_user)):
    return _user_to_out(current_user)
