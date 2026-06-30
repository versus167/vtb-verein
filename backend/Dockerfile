# Stage 1: Frontend bauen
FROM node:22-slim AS frontend-builder

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npx quasar build --mode pwa

# Stage 2: Python Backend
FROM python:3.12-slim

WORKDIR /app

# System-Dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Python-Dependencies
COPY vtb_verein/requirements.txt vtb_verein/requirements.txt
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r vtb_verein/requirements.txt -r backend/requirements.txt

# Anwendungscode
COPY vtb_verein/ ./vtb_verein/
COPY backend/ ./backend/

# Nur das Zutritts-Sync-Tool ins Image (für den Sync-Sidecar). Bewusst NICHT das ganze
# tools/-Verzeichnis: es enthält u. a. tickets.local.env (lokale Secrets).
COPY tools/zutritt_sync.py ./tools/zutritt_sync.py

# Versions-Datei – Quelle für get_app_version() bzw. /api/app-info.
# Muss in /app liegen (= Path(app_info.py).parents[3]), sonst Fallback auf 0.0.1.
COPY VERSION ./VERSION

# Frontend-Build aus Stage 1 kopieren
COPY --from=frontend-builder /frontend/dist/pwa/ ./frontend_dist/

# Non-root User
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser
RUN mkdir -p /data /app/uploads && chown -R appuser:appuser /data /app
USER appuser

ENV PYTHONPATH=/app/vtb_verein \
    VTB_HOST=0.0.0.0 \
    VTB_PORT=8000 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health').read()" || exit 1

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
