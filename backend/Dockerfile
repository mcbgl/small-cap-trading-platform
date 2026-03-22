# =============================================================================
# Backend Dockerfile - FastAPI + Python 3.12
# =============================================================================
# Build:  docker build -t trading-backend ./backend
# Run:    docker run -p 8000:8000 --env-file .env trading-backend
# =============================================================================

FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies required by asyncpg, numpy, etc.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifest first (layer caching)
COPY pyproject.toml ./

# Install Python dependencies using uv
# --system installs into the system Python (no virtualenv in container)
RUN uv pip install --system -e ".[dev]"

# Copy application source
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY tests/ ./tests/

# Expose the FastAPI port
EXPOSE 8000

# Run uvicorn with reload for development
# In production, remove --reload and use gunicorn + uvicorn workers
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "src"]
