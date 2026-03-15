from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.config import get_settings

settings = get_settings()

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.MONGO_URI)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()[settings.MONGO_DB]


async def connect_db() -> None:
    get_client()
    await get_db().command("ping")


async def close_db() -> None:
    global _client
    if _client:
        _client.close()
        _client = None


async def create_indexes() -> None:
    db = get_db()
    # Pays
    await db.countries.create_index([("country_code", 1)], unique=True)
    # Pharmacies
    await db.pharmacies.create_index([("city_id", 1)])
    await db.pharmacies.create_index([("name", "text")])
    await db.pharmacies.create_index([("location", "2dsphere")])
    # Gardes — index sur date unique
    await db.duty_schedules.create_index([("pharmacy_id", 1)])
    await db.duty_schedules.create_index([("date", 1)])
    # Villes — unicité par (name, country_code)
    await db.cities.create_index([("name", 1), ("country_code", 1)], unique=True)
    await db.cities.create_index([("country_code", 1)])
    # Users
    await db.users.create_index([("email", 1)], unique=True)
