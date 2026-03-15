#!/bin/sh
set -e

# Start scraper manager in background
python app/worker/scraper_manager.py &

# Start API (foreground)
exec gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:${PORT:-8000}
