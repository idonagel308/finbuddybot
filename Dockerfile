# Production Dockerfile for FinTechBot (Cloud Run Optimized)
FROM python:3.11-slim-bullseye

# Security & Operations
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

# System Dependencies (Required for building Python packages like numpy/matplotlib)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    libpng-dev \
    libfreetype6-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Dependency Layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application Source
# NOTE: .dockerignore ensures no local databases or keys are included
COPY . .

# Execution
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
