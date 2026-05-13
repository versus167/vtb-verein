# Stage 1: Frontend bauen
FROM node:20-slim AS frontend-builder

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci --omit=dev
COPY frontend/ ./
RUN npx quasar build

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

# Frontend-Build aus Stage 1 kopieren
COPY --from=frontend-builder /frontend/dist/spa/ ./frontend_dist/

# Non-root User
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser
RUN mkdir -p /data /app/uploads && chown -R appuser:appuser /data /app
USER appuser

ENV VTB_DB_PATH=/data/verein.db \
    VTB_HOST=0.0.0.0 \
    VTB_PORT=8000 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health').read()" || exit 1

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
