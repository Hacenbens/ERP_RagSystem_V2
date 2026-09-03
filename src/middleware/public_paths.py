"""
Public request paths — the single source of truth for both middlewares.

A path listed here carries no authenticated identity:
  - AuthMiddleware lets it through without a Bearer token.
  - RBACMiddleware skips it, because there is no role on request.state to check.

These two sets must never drift apart. A path that AuthMiddleware admits but
RBACMiddleware still guards would be rejected for a role it was never given,
which is precisely the failure this module exists to prevent.

Operational note: the OpenAPI paths (/docs, /redoc, /openapi.json) are public so
the interactive API explorer is reachable during development. Before an
internet-facing deployment, either drop them from this set or put the whole
service behind an authenticating proxy — they describe every route and schema.
"""
from __future__ import annotations

PUBLIC_PATHS: frozenset[str] = frozenset({
    # --- Operations ---------------------------------------------------------
    "/health",
    "/metrics",
    # --- Authentication (must be reachable to obtain a token) ---------------
    "/auth/register",
    "/auth/login",
    "/auth/request-password-reset",
    "/auth/reset-password",
    # --- OpenAPI / API explorer ---------------------------------------------
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
})

__all__ = ["PUBLIC_PATHS"]
