# Pharmaco API

> **Pharmaco** — Trouvez une pharmacie de garde en moins de 30 secondes.  
> Développé par [**Qinora**](https://qinora.bj) · Données synchronisées automatiquement par pays.

---

## Stack technique

| Couche          | Technologie                          |
|-----------------|--------------------------------------|
| API             | FastAPI + Gunicorn/Gevent            |
| Base de données | MongoDB 7 (Motor async)              |
| Cache           | Redis 7                              |
| Scraping        | httpx + BeautifulSoup (extensible)   |
| Auth            | JWT HS256 + bcrypt                   |
| Process manager | Supervisord                          |
| Reverse proxy   | Nginx                                |
| Conteneurs      | Docker + Docker Compose              |

---

## Démarrage rapide (Docker)

```bash
# 1. Configurer l'environnement
cp .env.example .env
# Éditer .env : changer SECRET_KEY au minimum

# 2. Lancer tous les services
docker compose up -d --build

# 3. Créer le premier superadmin (une seule fois)
curl -X POST http://localhost:8000/api/v1/auth/bootstrap \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@pharmaco.bj","password":"MotDePasse123!","role":"superadmin"}'

# 4. Seed immédiat (facultatif — le scraper tourne déjà en fond)
docker exec pharmaco_api python seed.py
```

---

## Démarrage sans Docker (dev)

```bash
# Prérequis : MongoDB et Redis lancés localement
pip install -r requirements.txt
cp .env.example .env

# Seed initial
python seed.py

# Via Supervisord
supervisord -c supervisord.conf

# Ou en mode dev direct
uvicorn app.main:app --reload --port 8000
```

---

## Documentation API

| URL                               | Description             |
|-----------------------------------|-------------------------|
| http://localhost:8000/api/docs    | Swagger UI interactif   |
| http://localhost:8000/api/redoc   | ReDoc                   |
| http://localhost:9001             | Supervisord Web UI      |

---

## Endpoints

### Pays disponibles (public)

| Méthode | URL                           | Description                                  |
|---------|-------------------------------|----------------------------------------------|
| `GET`   | `/api/v1/countries`           | Liste des pays avec stats                    |
| `GET`   | `/api/v1/countries/{code}`    | Détail d'un pays + villes                    |

### Villes (public)

| Méthode | URL                             | Description                         |
|---------|---------------------------------|-------------------------------------|
| `GET`   | `/api/v1/cities`                | Toutes les villes                   |
| `GET`   | `/api/v1/cities?country_code=BJ`| Villes filtrées par pays            |
| `GET`   | `/api/v1/cities/{id}`           | Détail d'une ville                  |

### Pharmacies (public)

| Méthode | URL                                            | Description                              |
|---------|------------------------------------------------|------------------------------------------|
| `GET`   | `/api/v1/pharmacies`                           | Liste (filtrables : pays, ville, garde)  |
| `GET`   | `/api/v1/pharmacies/on-duty-today`             | De garde aujourd'hui                     |
| `GET`   | `/api/v1/pharmacies/on-duty-today?country_code=BJ&city_name=Cotonou` | Filtrées |
| `GET`   | `/api/v1/pharmacies/nearby?latitude=6.36&longitude=2.42&radius_km=3` | Géoloc    |
| `GET`   | `/api/v1/pharmacies/nearby?...&on_duty_today=true` | Proches + de garde               |
| `GET`   | `/api/v1/pharmacies/{id}`                      | Détail d'une pharmacie                   |

### Gardes (public)

| Méthode | URL                                  | Description                           |
|---------|--------------------------------------|---------------------------------------|
| `GET`   | `/api/v1/duties/today`               | Gardes du jour                        |
| `GET`   | `/api/v1/duties/today?country_code=BJ&city_name=Porto-Novo` | Filtrées    |
| `GET`   | `/api/v1/duties`                     | Toutes les gardes validées            |
| `GET`   | `/api/v1/duties/{id}`                | Détail d'une garde                    |

### Statistiques (public)

| Méthode | URL             | Description                                         |
|---------|-----------------|-----------------------------------------------------|
| `GET`   | `/api/v1/stats` | KPIs globaux : pharmacies, villes, gardes du jour   |

### Admin (Bearer token requis)

| Méthode  | URL                               | Description                     |
|----------|-----------------------------------|---------------------------------|
| `POST`   | `/api/v1/auth/bootstrap`          | Créer le 1er superadmin (1×)    |
| `POST`   | `/api/v1/auth/login`              | Obtenir un JWT                  |
| `GET`    | `/api/v1/auth/me`                 | Profil courant                  |
| `POST`   | `/api/v1/auth/register`           | Créer un admin                  |
| `POST`   | `/api/v1/pharmacies`              | Ajouter une pharmacie           |
| `PATCH`  | `/api/v1/pharmacies/{id}`         | Modifier une pharmacie          |
| `DELETE` | `/api/v1/pharmacies/{id}`         | Supprimer une pharmacie         |
| `POST`   | `/api/v1/duties`                  | Créer une garde (date unique)   |
| `PATCH`  | `/api/v1/duties/{id}/validate`    | Valider une garde               |
| `POST`   | `/api/v1/cities`                  | Ajouter une ville               |
| `PATCH`  | `/api/v1/cities/{id}`             | Modifier une ville              |
| `DELETE` | `/api/v1/cities/{id}`             | Supprimer une ville             |
| `GET`    | `/api/v1/stats/scraper`           | Statut des scrapers par source  |
| `GET`    | `/api/v1/stats/duties/pending`    | Gardes en attente de validation |

---

## Architecture scraper multi-pays

```
app/worker/
├── base_scraper.py        ← Classe abstraite (fetch → parse → sync)
├── scraper_registry.py    ← @register_scraper + autodiscovery
├── scraper_manager.py     ← Lance TOUS les scrapers en parallèle
└── sources/
    ├── __init__.py        ← Guide : comment ajouter un pays
    └── bj_ubphar.py       ← ✅ Bénin — ubphar.com
```

### Ajouter un nouveau pays

1. Créer `app/worker/sources/<cc>_<source>.py`  
   (ex: `tg_monpharmacien.py` pour le Togo)

2. Écrire la classe :

```python
from app.worker.base_scraper import BaseScraper
from app.worker.scraper_registry import register_scraper
import httpx

@register_scraper
class TogoScraper(BaseScraper):
    country_code = "TG"
    country_name = "Togo"
    source_url   = "https://exemple-source.tg/pharmacies"
    source_name  = "exemple"

    async def fetch(self) -> str:
        async with httpx.AsyncClient() as c:
            return (await c.get(self.source_url)).text

    def parse(self, raw: str) -> list[dict]:
        # Parser spécifique à la source
        return [
            {"name": "Pharmacie X", "city_name": "LOMÉ", "phone": "..."},
        ]
```

3. Redémarrer le service — **aucune autre modification requise**.  
   Le pays apparaît automatiquement dans `/api/v1/countries`.

---

## Structure du projet

```
pharmaco/
├── app/
│   ├── main.py                    ← FastAPI (lifespan, CORS, routers)
│   ├── config.py                  ← Settings Pydantic (.env)
│   ├── database.py                ← Motor + index MongoDB
│   ├── core/
│   │   └── security.py            ← JWT, bcrypt, require_admin
│   ├── schemas/                   ← Modèles Pydantic I/O
│   │   ├── city.py
│   │   ├── pharmacy.py
│   │   ├── duty.py
│   │   └── user.py
│   ├── routers/                   ← Endpoints REST
│   │   ├── auth.py
│   │   ├── countries.py           ← /countries (public)
│   │   ├── cities.py
│   │   ├── pharmacies.py
│   │   ├── duties.py
│   │   └── stats.py               ← KPIs
│   └── worker/
│       ├── base_scraper.py        ← Contrat abstrait
│       ├── scraper_registry.py    ← Registre + autodiscovery
│       ├── scraper_manager.py     ← Orchestrateur
│       └── sources/
│           └── bj_ubphar.py       ← Source Bénin
├── logs/
├── seed.py                        ← Seed initial
├── supervisord.conf
├── Dockerfile
├── docker-compose.yml
├── nginx.conf
├── requirements.txt
└── .env.example
```

---

## Variables d'environnement

| Variable                    | Défaut                   | Description                    |
|-----------------------------|--------------------------|--------------------------------|
| `SECRET_KEY`                | `change-me`              | Clé JWT — **obligatoire**      |
| `MONGO_URI`                 | `mongodb://localhost`    | URI MongoDB                    |
| `MONGO_DB`                  | `pharmaco`               | Nom de la base                 |
| `REDIS_URL`                 | `redis://localhost:6379` | URI Redis                      |
| `SCRAPER_INTERVAL_HOURS`    | `24`                     | Fréquence du scraping          |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440`                 | Durée de vie du JWT (24h)      |

---

## Évolutions futures

- [ ] Enrichissement GPS via Nominatim (OpenStreetMap) ou Google Geocoding API
- [ ] Notifications push FCM quand une garde est validée
- [ ] Application mobile React Native
- [ ] Partenariat Ordre des Pharmaciens du Bénin
- [ ] Scraper Togo, Sénégal, Côte d'Ivoire…
- [ ] Import planning des gardes en bulk (CSV admin)
