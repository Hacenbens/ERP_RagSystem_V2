"""
Central configuration — reads from environment variables.
All evaluation thresholds and service settings live here.
"""
from __future__ import annotations

import os


# ---------------------------------------------------------------------------
# Evaluation thresholds (Sprint 2)
# ---------------------------------------------------------------------------
SQL_SUCCESS_MIN: float = float(os.environ.get("SQL_SUCCESS_MIN", "0.95"))
HALLUCINATION_MAX: float = float(os.environ.get("HALLUCINATION_MAX", "0.05"))
RAG_PRECISION_MIN: float = float(os.environ.get("RAG_PRECISION_MIN", "0.70"))

# ---------------------------------------------------------------------------
# ERP PostgreSQL (read-only — Sprint 4 SQL pipeline)
# ---------------------------------------------------------------------------
ERP_PG_HOST: str = os.environ.get("ERP_PG_HOST", "localhost")
ERP_PG_PORT: int = int(os.environ.get("ERP_PG_PORT", "5432"))
ERP_PG_DATABASE: str = os.environ.get("ERP_PG_DATABASE", "erp_prod")
ERP_PG_USER: str = os.environ.get("ERP_PG_USER", "erp_readonly")
ERP_PG_PASSWORD: str = os.environ.get("ERP_PG_PASSWORD", "")

# ---------------------------------------------------------------------------
# LLM / Embedding
# ---------------------------------------------------------------------------
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
LLM_MODEL: str = os.environ.get("LLM_MODEL", "gpt-4o")
EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-large")

# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
JWT_SECRET_KEY: str = os.environ.get("JWT_SECRET_KEY", "change_me_in_production")
JWT_ALGORITHM: str = os.environ.get("JWT_ALGORITHM", "RS256")
JWT_EXPIRY_MINUTES: int = int(os.environ.get("JWT_EXPIRY_MINUTES", "60"))
