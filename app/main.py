from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import connect_db, close_db, create_indexes
from app.routers import auth, cities, countries, pharmacies, duties, stats

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_db()
    await create_indexes()
    yield
    await close_db()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        f"**{settings.APP_NAME}** — Trouvez une pharmacie de garde en moins de 30 secondes.\n\n"
        f"Une solution [**{settings.APP_COMPANY}**](https://qinora.bj). "
        "Données synchronisées automatiquement depuis les sources officielles par pays."
    ),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Restreindre en production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PREFIX = "/api/v1"
app.include_router(auth.router,       prefix=PREFIX)
app.include_router(countries.router,  prefix=PREFIX)
app.include_router(cities.router,     prefix=PREFIX)
app.include_router(pharmacies.router, prefix=PREFIX)
app.include_router(duties.router,     prefix=PREFIX)
app.include_router(stats.router,      prefix=PREFIX)


@app.get("/health", tags=["Health"])
async def health():
    return JSONResponse({
        "status": "ok",
        "app": settings.APP_NAME,
        "by": settings.APP_COMPANY,
        "version": settings.APP_VERSION,
    })


@app.get("/", include_in_schema=False)
async def root():
    return JSONResponse({
        "app": settings.APP_NAME,
        "by": settings.APP_COMPANY,
        "version": settings.APP_VERSION,
        "docs": "/api/docs",
    })
