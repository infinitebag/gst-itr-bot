# ---------------------------------------------------------------------------
# Multi-stage Dockerfile for GST + ITR WhatsApp Bot
#
#   Production image:  docker build --target production -t gst-bot .
#   Development image: docker build --target development -t gst-bot-dev .
#   Default (no --target): builds the development image
# ---------------------------------------------------------------------------

# ========================== BASE STAGE ======================================
# Shared system dependencies for both dev and production.
FROM python:3.10-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (Postgres driver, OCR, PDF tools)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    libpq-dev \
    tesseract-ocr \
    libtesseract-dev \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# ========================== PRODUCTION STAGE ================================
# Installs only base (runtime) dependencies — no pytest, ruff, black, etc.
FROM base AS production

COPY requirements-base.txt ./
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements-base.txt

COPY . .

# Run as non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ========================== DEVELOPMENT STAGE ===============================
# Installs dev + base dependencies (pytest, ruff, black, opencv, etc.)
# This is the DEFAULT target when no --target is specified.
FROM base AS development

COPY requirements-base.txt requirements-dev.txt ./
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements-dev.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
