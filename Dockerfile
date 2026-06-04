FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ca-certificates + curl for healthcheck; gosu to drop privileges in entrypoint.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gosu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY brain ./brain
COPY api ./api
COPY mcp_server ./mcp_server
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create the non-root user the entrypoint will drop to.
RUN useradd --create-home --uid 10001 brain && mkdir -p /data && chown -R brain:brain /app /data

ENV BRAIN_DATA_DIR=/data \
    EMBED_CACHE_DIR=/data/models \
    API_HOST=0.0.0.0 \
    API_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Entrypoint runs as root (fixes /data perms), then execs uvicorn as 'brain'.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
