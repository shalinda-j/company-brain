"""Configuration for Company Brain. All settings come from environment variables.

Nothing secret is hard-coded. Secrets (API keys) are read from the environment
and never written to logs.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv is optional at runtime
    pass


def _bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass
class Config:
    # --- Storage ---------------------------------------------------------
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("BRAIN_DATA_DIR", "./data")).resolve())

    # --- Vector store (Qdrant) ------------------------------------------
    # If QDRANT_URL is set, connect to a Qdrant server. Otherwise fall back to
    # an embedded on-disk Qdrant under data_dir/qdrant (no server needed).
    qdrant_url: str | None = field(default_factory=lambda: os.getenv("QDRANT_URL") or None)
    qdrant_api_key: str | None = field(default_factory=lambda: os.getenv("QDRANT_API_KEY") or None)
    qdrant_collection: str = field(default_factory=lambda: os.getenv("QDRANT_COLLECTION", "company_brain"))

    # --- Embeddings ------------------------------------------------------
    # Default is a multilingual model so Sinhala + English + code all work.
    # Lighter/faster:  sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (384-dim)
    # Best quality:    intfloat/multilingual-e5-large (1024-dim, heavier on CPU)
    embed_model: str = field(
        default_factory=lambda: os.getenv(
            "EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
        )
    )
    embed_cache_dir: str | None = field(default_factory=lambda: os.getenv("EMBED_CACHE_DIR") or None)

    # --- Chunking --------------------------------------------------------
    chunk_size: int = field(default_factory=lambda: _int("CHUNK_SIZE", 1000))
    chunk_overlap: int = field(default_factory=lambda: _int("CHUNK_OVERLAP", 150))

    # --- API server ------------------------------------------------------
    api_host: str = field(default_factory=lambda: os.getenv("API_HOST", "0.0.0.0"))
    api_port: int = field(default_factory=lambda: _int("API_PORT", 8000))
    # Comma-separated list of "key:agent" pairs, e.g. "abc123:claude-code,def456:cursor"
    # A bare key with no agent defaults to agent name "default".
    api_keys_raw: str = field(default_factory=lambda: os.getenv("BRAIN_API_KEYS", ""))
    cors_origins: str = field(default_factory=lambda: os.getenv("CORS_ORIGINS", ""))
    rate_limit: str = field(default_factory=lambda: os.getenv("RATE_LIMIT", "120/minute"))
    max_body_bytes: int = field(default_factory=lambda: _int("MAX_BODY_BYTES", 2_000_000))

    # --- Behaviour -------------------------------------------------------
    # When true, every search query is itself saved into the brain's activity log
    # so the brain "remembers" everything you searched for.
    log_searches: bool = field(default_factory=lambda: _bool("LOG_SEARCHES", True))

    @property
    def vault_dir(self) -> Path:
        return self.data_dir / "vault"

    @property
    def qdrant_path(self) -> Path:
        return self.data_dir / "qdrant"

    @property
    def audit_log_path(self) -> Path:
        return self.data_dir / "audit.log"

    def ensure_dirs(self) -> None:
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        for sub in ("conversations", "notes", "tasks", "knowledge", "activity"):
            (self.vault_dir / sub).mkdir(parents=True, exist_ok=True)
        if not self.qdrant_url:
            self.qdrant_path.mkdir(parents=True, exist_ok=True)


config = Config()
