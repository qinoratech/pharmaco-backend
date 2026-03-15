FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ── Dépendances système ───────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Dépendances Python ────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# ── Code source ───────────────────────────────────────────────────
COPY . .

# ── Répertoire des logs ───────────────────────────────────────────
RUN mkdir -p /app/logs

# ── Port exposé ───────────────────────────────────────────────────
EXPOSE 8000 9001

# ── Démarrage via Supervisord ─────────────────────────────────────
CMD ["supervisord", "-c", "/app/supervisord.conf"]
