FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    EASYOCR_MODULE_PATH=/app/.easyocr

WORKDIR /app

# ── Dépendances système ───────────────────────────────────────────
# libgl1 + libglib2.0-0 : requis par OpenCV (dépendance d'EasyOCR)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libgl1 \
    libglib2.0-0 \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

# ── Dépendances Python + préchargement modèles EasyOCR ───────────
# torch/torchvision CPU-only installés en premier (évite ~800 Mo CUDA)
# Modèles EasyOCR baked dans l'image → aucun téléchargement au runtime
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu && \
    pip install -r requirements.txt && \
    python -c "import easyocr; easyocr.Reader(['fr', 'en'], gpu=False, verbose=False, model_storage_directory='/app/.easyocr')"

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
