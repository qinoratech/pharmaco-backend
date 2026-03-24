FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ── Dépendances système ───────────────────────────────────────────
# tesseract-ocr-fra : modèle de langue française pour l'OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libxml2-dev \
    libxslt-dev \
    tesseract-ocr \
    tesseract-ocr-fra \
    && rm -rf /var/lib/apt/lists/*

# ── Dépendances Python ────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# ── Code source ───────────────────────────────────────────────────
COPY . .

# ── Répertoire des logs ───────────────────────────────────────────
RUN mkdir -p /app/logs

# ── Port exposé ───────────────────────────────────────────────────
EXPOSE 8000

# ── Démarrage ─────────────────────────────────────
COPY start.sh .
RUN chmod +x start.sh
CMD ["./start.sh"]
