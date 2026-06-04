FROM python:3.12-slim

# Non-interactive, no .pyc, unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps kept minimal. fastembed/onnxruntime ship manylinux wheels.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY brain ./brain
COPY api ./api
COPY mcp_server ./mcp_server

# Run as a non-root user for safety.
RUN useradd --create-home --uid 10001 brain \
    && mkdir -p /data \
    && chown -R brain:brain /app /data
USER brain

ENV BRAIN_DATA_DIR=/data \
    EMBED_CACHE_DIR=/data/models \
    API_HOST=0.0.0.0 \
    API_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
