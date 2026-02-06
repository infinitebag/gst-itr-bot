FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (Postgres + OCR)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    libpq-dev \
    tesseract-ocr \
    libtesseract-dev \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# ✅ Copy BOTH requirement files because dev includes base via -r
COPY requirements-base.txt requirements-dev.txt ./

RUN pip install --upgrade pip \
    && pip install -r requirements-dev.txt

# App code
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]