"""
Central configuration — reads from environment variables.
All evaluation thresholds and service settings live here.
"""
from __future__ import annotations

import os


def _env(name: str, default: str) -> str:
    """Return env var *name*, treating an empty value as absent.

    A set-but-empty variable must not be more harmful than an unset one.
    GitHub Actions injects every unconfigured repository secret as an empty
    string, so `os.environ.get("ERP_PG_PORT", "5432")` returned "" and
    `int("")` raised at import time, taking down anything that imported this
    module. The same happens with a half-filled .env in any environment.
    """
    value = os.environ.get(name, "")
    return value if value.strip() else default


# ---------------------------------------------------------------------------
# Evaluation thresholds (Sprint 2)
# ---------------------------------------------------------------------------
SQL_SUCCESS_MIN: float = float(_env("SQL_SUCCESS_MIN", "0.95"))
HALLUCINATION_MAX: float = float(_env("HALLUCINATION_MAX", "0.05"))
RAG_PRECISION_MIN: float = float(_env("RAG_PRECISION_MIN", "0.70"))

# ---------------------------------------------------------------------------
# ERP PostgreSQL (read-only — Sprint 4 SQL pipeline)
# ---------------------------------------------------------------------------
ERP_PG_HOST: str = _env("ERP_PG_HOST", "localhost")
ERP_PG_PORT: int = int(_env("ERP_PG_PORT", "5432"))
ERP_PG_DATABASE: str = _env("ERP_PG_DATABASE", "erp_prod")
ERP_PG_USER: str = _env("ERP_PG_USER", "erp_readonly")
ERP_PG_PASSWORD: str = _env("ERP_PG_PASSWORD", "")


def erp_pg_dsn() -> str:
    """Return the ERP PostgreSQL DSN, or "" when no database is configured.

    QueryExecutor used to read an ERP_PG_DSN environment variable that is set
    nowhere — not in .env, .env.example, docker-compose, or CI. Only the
    ERP_PG_* parts exist, and nothing assembled them, so the executor always
    fell through to InMemoryExecutor and answered with synthetic rows.

    A password is required: connecting to the real ERP as the read-only user
    without one is not something to attempt implicitly. Absent it, callers
    get "" and must present their results as synthetic.
    """
    if not ERP_PG_PASSWORD:
        return ""
    return (
        f"postgresql://{ERP_PG_USER}:{ERP_PG_PASSWORD}"
        f"@{ERP_PG_HOST}:{ERP_PG_PORT}/{ERP_PG_DATABASE}"
    )

# ---------------------------------------------------------------------------
# LLM / Embedding
# ---------------------------------------------------------------------------
OPENAI_API_KEY: str = _env("OPENAI_API_KEY", "")
LLM_MODEL: str = _env("LLM_MODEL", "gpt-4o")
EMBEDDING_MODEL: str = _env("EMBEDDING_MODEL", "text-embedding-3-large")

# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
JWT_SECRET_KEY: str = _env("JWT_SECRET_KEY", "change_me_in_production")
JWT_ALGORITHM: str = _env("JWT_ALGORITHM", "RS256")
JWT_EXPIRY_MINUTES: int = int(_env("JWT_EXPIRY_MINUTES", "60"))
