"""Configuration for Company Brain v2. All settings come from environment
variables. Nothing secret is hard-coded; secrets are read from the environment
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


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass
class Config:
    # --- Storage ---------------------------------------------------------
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("BRAIN_DATA_DIR", "./data")).resolve()
    )

    # --- Projects --------------------------------------------------------
    # Each project is isolated: its own vault subfolder and its own Qdrant
    # collection. A request without a project falls back to this default.
    default_project: str = field(
        default_factory=lambda: os.getenv("BRAIN_DEFAULT_PROJECT", "default")
    )

    # --- Vector store (Qdrant) ------------------------------------------
    qdrant_url: str | None = field(default_factory=lambda: os.getenv("QDRANT_URL") or None)
    qdrant_api_key: str | None = field(default_factory=lambda: os.getenv("QDRANT_API_KEY") or None)
    # Base name; the real collection is f"{base}__{project}".
    qdrant_collection: str = field(
        default_factory=lambda: os.getenv("QDRANT_COLLECTION", "company_brain")
    )

    # --- Embeddings (local, CPU) ----------------------------------------
    embed_model: str = field(
        default_factory=lambda: os.getenv(
            "EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
    )
    embed_cache_dir: str | None = field(
        default_factory=lambda: os.getenv("EMBED_CACHE_DIR") or None
    )

    # --- Chunking --------------------------------------------------------
    chunk_size: int = field(default_factory=lambda: _int("CHUNK_SIZE", 1000))
    chunk_overlap: int = field(default_factory=lambda: _int("CHUNK_OVERLAP", 150))

    # --- Self-optimization / safe learning ------------------------------
    # On save, if a near-identical memory already exists (cosine >= threshold),
    # treat it as a duplicate instead of storing a second copy.
    safe_save: bool = field(default_factory=lambda: _bool("SAFE_SAVE", True))
    dedup_threshold: float = field(default_factory=lambda: _float("DEDUP_THRESHOLD", 0.96))
    # Search re-ranking: blend semantic score with a memory's usefulness/access.
    feedback_weight: float = field(default_factory=lambda: _float("FEEDBACK_WEIGHT", 0.15))
    access_weight: float = field(default_factory=lambda: _float("ACCESS_WEIGHT", 0.10))
    # How many extra candidates to fetch before re-ranking.
    search_overfetch: int = field(default_factory=lambda: _int("SEARCH_OVERFETCH", 3))

    # --- Multi-layer recall ---------------------------------------------
    recall_token_budget: int = field(default_factory=lambda: _int("RECALL_TOKEN_BUDGET", 1500))

    # --- Dreaming (reflection) ------------------------------------------
    # Cluster notes whose similarity is in [relate, dedup) into digest notes.
    dream_relate_threshold: float = field(
        default_factory=lambda: _float("DREAM_RELATE_THRESHOLD", 0.6)
    )
    dream_max_digests: int = field(default_factory=lambda: _int("DREAM_MAX_DIGESTS", 10))

    # --- Heartbeat + autonomous learning --------------------------------
    # Background maintenance interval in seconds (0 = disabled; run manually).
    heartbeat_interval: int = field(default_factory=lambda: _int("HEARTBEAT_INTERVAL", 0))
    # How much unused memories lose per heartbeat (use-it-or-lose-it).
    decay_step: int = field(default_factory=lambda: _int("DECAY_STEP", 1))

    # --- Hybrid retrieval -----------------------------------------------
    hybrid_search: bool = field(default_factory=lambda: _bool("HYBRID_SEARCH", True))
    rrf_k: int = field(default_factory=lambda: _int("RRF_K", 60))

    # --- Core memory blocks ---------------------------------------------
    block_char_limit: int = field(default_factory=lambda: _int("BLOCK_CHAR_LIMIT", 2000))

    # --- Safety: secret/PII redaction -----------------------------------
    # When True, detected secrets are replaced before storing. When False, they
    # are only reported back to the caller (findings) without modifying content.
    redact_on_save: bool = field(default_factory=lambda: _bool("REDACT_ON_SAVE", False))

    # --- Sleep cycle ----------------------------------------------------
    # When True, the heartbeat's sleep cycle archives stale, low-value memories.
    sleep_archive: bool = field(default_factory=lambda: _bool("SLEEP_ARCHIVE", False))

    # --- Optional LLM summarization for /ingest -------------------------
    # OFF by default to preserve the local-only / private posture. When on and
    # an API key is configured, /ingest summarizes long text before storing.
    summarize: bool = field(default_factory=lambda: _bool("BRAIN_SUMMARIZE", False))
    llm_provider: str = field(default_factory=lambda: os.getenv("BRAIN_LLM_PROVIDER", "anthropic"))
    llm_api_key: str | None = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY") or os.getenv("BRAIN_LLM_API_KEY")
    )
    llm_model: str = field(
        default_factory=lambda: os.getenv("BRAIN_LLM_MODEL", "claude-3-5-haiku-latest")
    )

    # --- API server ------------------------------------------------------
    api_host: str = field(default_factory=lambda: os.getenv("API_HOST", "0.0.0.0"))
    api_port: int = field(default_factory=lambda: _int("API_PORT", 8000))
    api_keys_raw: str = field(default_factory=lambda: os.getenv("BRAIN_API_KEYS", ""))
    cors_origins: str = field(default_factory=lambda: os.getenv("CORS_ORIGINS", ""))
    rate_limit: str = field(default_factory=lambda: os.getenv("RATE_LIMIT", "120/minute"))
    max_body_bytes: int = field(default_factory=lambda: _int("MAX_BODY_BYTES", 4_000_000))

    # --- Behaviour -------------------------------------------------------
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

    def collection_for(self, project: str) -> str:
        return f"{self.qdrant_collection}__{project}"

    def ensure_dirs(self) -> None:
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        if not self.qdrant_url:
            self.qdrant_path.mkdir(parents=True, exist_ok=True)


config = Config()
