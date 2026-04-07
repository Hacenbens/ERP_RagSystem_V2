"""
RBACMiddleware — role-based access control + ERP module guard (Sprint 1 stub).

Position in stack: FOURTH (after RateLimitMiddleware).

Roles (defined in source-of-truth):
    ADMIN    — unrestricted access to all routes and ERP modules
    MANAGER  — read/write on all modules except admin routes
    ANALYST  — read-only on permitted modules (no finance_schema by default)
    VIEWER   — read-only on RAG query endpoint only

ModuleAccessGuard is embedded here (NOT a separate file per Architecture Mapping).
It filters allowed SQL tables and RAG collections based on erp_rbac_policy.py.

Sprint 1 stub behaviour:
    - Reads role from request.state.role (set by AuthMiddleware)
    - Blocks access to /admin/* for non-ADMIN roles → 403
    - Increments RBAC_VIOLATION_RATE on every block
    - All other route/role combinations pass through

Sprint 5 will add:
    - Full route × role permission matrix
    - ERP module whitelist check via erp_rbac_policy.py
"""
from __future__ import annotations

from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.observability.prometheus_metrics import MIDDLEWARE_VIOLATIONS, RBAC_VIOLATION_RATE
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

# Routes restricted to ADMIN role only
_ADMIN_ONLY_PREFIX: str = "/admin"

# Roles that may access admin routes
_ADMIN_ROLES: frozenset[str] = frozenset({"ADMIN"})


class RBACMiddleware(BaseHTTPMiddleware):
    """Enforce role-based access control on every authenticated request.

    ModuleAccessGuard logic is embedded in this class per Architecture Mapping:
    the ERP module whitelist (which SQL tables / RAG collections each role can
    access) will be enforced here in Sprint 5 via erp_rbac_policy.py.

    Sprint 1: blocks non-ADMIN users from /admin/* endpoints.
    Sprint 5: enforces full route × role × module permission matrix.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Check role permissions; return 403 on violation."""
        role: str = getattr(request.state, "role", "VIEWER")
        path: str = request.url.path

        # --- Admin route guard -------------------------------------------
        if path.startswith(_ADMIN_ONLY_PREFIX) and role not in _ADMIN_ROLES:
            RBAC_VIOLATION_RATE.labels(role=role, resource=path).inc()
            MIDDLEWARE_VIOLATIONS.labels(middleware="rbac").inc()
            logger.warning(
                "rbac.access_denied",
                role=role,
                path=path,
                required_role="ADMIN",
            )
            return JSONResponse(
                status_code=403,
                content={"detail": f"Role '{role}' is not permitted to access {path}."},
            )

        # Sprint 5: module-level guard will be inserted here
        # allowed_modules = erp_rbac_policy.get_allowed_modules(role)
        # if requested_module not in allowed_modules: → 403

        return await call_next(request)


__all__ = ["RBACMiddleware"]
