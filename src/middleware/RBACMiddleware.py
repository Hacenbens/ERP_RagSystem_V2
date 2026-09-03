"""
RBACMiddleware — role-based access control + ERP module guard (Sprint 5).

Position in stack: FOURTH (after RateLimitMiddleware).

Roles (src/domain/user_role.py — source of truth § 8.1):
    SUPER_ADMIN         — unrestricted access to all routes and ERP modules
    PRODUCT_MANAGER     — inventory, procurement, CRM (SQL + RAG)
    INVENTORY_MANAGER   — inventory, warehouse (SQL + RAG)
    FINANCE_MANAGER     — finance, reporting (SQL + RAG)
    WAREHOUSE_OPERATOR  — warehouse (SQL + RAG); inventory (RAG only)
    PROCUREMENT_MANAGER — procurement, inventory (SQL + RAG)
    CRM_AGENT           — CRM (SQL + RAG); reporting (RAG only)
    LOGISTICS_AGENT     — logistics, warehouse (SQL + RAG)
    REPORTING_ANALYST   — RAG only on all modules; SQL always denied

ModuleAccessGuard is embedded here (NOT a separate file per Architecture Mapping).
It delegates to erp_rbac_policy.py for the SQL table / RAG collection whitelist.

Guards (in order):
    1. Admin route guard   — /admin/* → SUPER_ADMIN only → 403 for others
    2. SQL module guard    — /api/erp/query SQL path:
          a. REPORTING_ANALYST blocked entirely (no SQL access)
          b. request.state.erp_module set  → check module permission
          c. request.state.erp_table  set  → check is_table_allowed()
"""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.domain.erp_module import ErpModule
from src.domain.user_role import UserRole
from src.infrastructure.auth.erp_rbac_policy import (
    get_allowed_modules,
    is_table_allowed,
)
from src.middleware.public_paths import PUBLIC_PATHS
from src.observability.prometheus_metrics import MIDDLEWARE_VIOLATIONS, RBAC_VIOLATION_RATE
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)

# Routes restricted to SUPER_ADMIN only
_ADMIN_ONLY_PREFIX: str = "/admin"

# SQL query path subject to module-level guard
_SQL_QUERY_PATH: str = "/api/erp/query"


def _403(role: str, detail: str, resource: str) -> JSONResponse:
    RBAC_VIOLATION_RATE.labels(role=role, resource=resource).inc()
    MIDDLEWARE_VIOLATIONS.labels(middleware="rbac_module").inc()
    logger.warning("rbac.access_denied", role=role, resource=resource, detail=detail)
    return JSONResponse(status_code=403, content={"detail": detail})


class RBACMiddleware(BaseHTTPMiddleware):
    """Enforce role-based access control on every authenticated request.

    ModuleAccessGuard logic is embedded in this class per Architecture Mapping.
    Sprint 5: full route × role × module permission matrix via erp_rbac_policy.py.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Check role permissions; return 403 on violation."""
        path: str = request.url.path

        # Public paths never reached AuthMiddleware's verification, so
        # request.state carries no role to check. Skip before reading it.
        if path in PUBLIC_PATHS:
            return await call_next(request)

        role: str = getattr(request.state, "role", UserRole.REPORTING_ANALYST.value)

        # ------------------------------------------------------------------
        # Guard 1 — Admin route: SUPER_ADMIN only
        # ------------------------------------------------------------------
        if path.startswith(_ADMIN_ONLY_PREFIX) and role != UserRole.SUPER_ADMIN:
            return _403(
                role=role,
                detail=f"Role '{role}' is not permitted to access {path}.",
                resource=path,
            )

        # ------------------------------------------------------------------
        # Guard 2 — SQL module guard: /api/erp/query
        # ------------------------------------------------------------------
        if path.startswith(_SQL_QUERY_PATH):
            violation = self._check_sql_module_guard(role, request)
            if violation is not None:
                return violation

        return await call_next(request)

    # ------------------------------------------------------------------
    # Module guard helpers
    # ------------------------------------------------------------------

    def _check_sql_module_guard(
        self, role: str, request: Request
    ) -> Optional[JSONResponse]:
        """Return a 403 response if the role is not permitted on the SQL path.

        Checks (in order):
        1. REPORTING_ANALYST → always denied (RAG-only role).
        2. request.state.erp_module → check module-level can_sql permission.
        3. request.state.erp_table  → resolve table → module → check can_sql.
        Returns None if all checks pass.
        """
        # 2a — REPORTING_ANALYST: zero SQL access
        if role == UserRole.REPORTING_ANALYST:
            return _403(
                role=role,
                detail=(
                    f"Role '{role}' is not permitted on the SQL path. "
                    "Use the RAG endpoint instead."
                ),
                resource=_SQL_QUERY_PATH,
            )

        # 2b — module injected via request.state.erp_module
        erp_module: Optional[str] = getattr(request.state, "erp_module", None)
        if erp_module is not None:
            allowed_modules = get_allowed_modules(role)
            try:
                module_enum = ErpModule(erp_module)
            except ValueError:
                # Unknown module name → deny
                return _403(
                    role=role,
                    detail=f"Unknown ERP module '{erp_module}'.",
                    resource=_SQL_QUERY_PATH,
                )
            perm = allowed_modules.get(module_enum)
            if perm is None or not perm.can_sql:
                return _403(
                    role=role,
                    detail=f"Module '{erp_module}' not permitted for role '{role}'.",
                    resource=_SQL_QUERY_PATH,
                )

        # 2c — table injected via request.state.erp_table
        erp_table: Optional[str] = getattr(request.state, "erp_table", None)
        if erp_table is not None and not is_table_allowed(role, erp_table):
            # Resolve module name for the error message
            from src.infrastructure.auth.erp_rbac_policy import _TABLE_MODULE_MAP  # noqa: PLC0415
            module_label = _TABLE_MODULE_MAP.get(erp_table, ErpModule.ADMIN).value
            return _403(
                role=role,
                detail=f"Module '{module_label}' not permitted for role '{role}'.",
                resource=_SQL_QUERY_PATH,
            )

        return None


__all__ = ["RBACMiddleware"]
