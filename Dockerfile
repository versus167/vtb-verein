# Stage 1: Builder - Dependencies installieren
FROM python:3.11-slim AS builder

WORKDIR /build

# System-Dependencies für Builds (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Requirements kopieren und Dependencies in /install installieren
COPY vtb_verein/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime - Produktions-Image
FROM python:3.11-slim

# Metadata
LABEL maintainer="VTB Verein"
LABEL description="VTB Vereinsverwaltung - Docker Image"

# Python Packages aus Builder-Stage kopieren
COPY --from=builder /install /usr/local

# Anwendungscode kopieren
WORKDIR /app
COPY vtb_verein/ ./vtb_verein/
COPY .env.example ./

# Non-root User erstellen
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

# Data-Verzeichnis für SQLite erstellen und Rechte setzen
RUN mkdir -p /data && \
    chown -R appuser:appuser /data /app

# Zu non-root User wechseln
USER appuser

# Working Directory auf vtb_verein setzen (für korrekte Python-Imports)
WORKDIR /app/vtb_verein

# Default Environment Variables
ENV VTB_DB_PATH=/data/verein.db \
    VTB_HOST=0.0.0.0 \
    VTB_PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Port dokumentieren
EXPOSE 8080

# Health Check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080').read()" || exit 1

# Startkommando (aus /app/vtb_verein)
CMD ["python", "main.py"]