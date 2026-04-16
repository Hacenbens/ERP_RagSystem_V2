"""
ERP RBAC Policy — module-level access control (Sprint 5, Task 2).

Defines MODULE_ACCESS_MATRIX and the three policy functions consumed by
RBACMiddleware to enforce module-level guards on SQL and RAG paths.

Source of truth: erp_rag_claude_code/docs/source_of_truth.md § 8.5

Public API
──────────
get_allowed_modules(role)           → dict[ErpModule, ModulePermission]
is_table_allowed(role, table_name)  → bool
is_collection_allowed(role, coll)   → bool
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.domain.erp_module import ErpModule
from src.domain.user_role import UserRole
from src.observability.structured_logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Permission primitive
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModulePermission:
    """Pair of flags controlling SQL and RAG access for one module."""

    can_sql: bool
    can_rag: bool


_FULL     = ModulePermission(can_sql=True,  can_rag=True)
_RAG_ONLY = ModulePermission(can_sql=False, can_rag=True)


# ---------------------------------------------------------------------------
# § 8.5 — MODULE_ACCESS_MATRIX
# ---------------------------------------------------------------------------

MODULE_ACCESS_MATRIX: dict[UserRole, dict[ErpModule, ModulePermission]] = {
    UserRole.SUPER_ADMIN: {m: _FULL for m in ErpModule},

    UserRole.PRODUCT_MANAGER: {
        ErpModule.INVENTORY:   _FULL,
        ErpModule.PROCUREMENT: _FULL,
        ErpModule.CRM:         _FULL,
        ErpModule.REPORTING:   _RAG_ONLY,
    },

    UserRole.INVENTORY_MANAGER: {
        ErpModule.INVENTORY:  _FULL,
        ErpModule.WAREHOUSE:  _FULL,
        ErpModule.REPORTING:  _RAG_ONLY,
    },

    UserRole.FINANCE_MANAGER: {
        ErpModule.FINANCE:    _FULL,
        ErpModule.REPORTING:  _FULL,
    },

    UserRole.WAREHOUSE_OPERATOR: {
        ErpModule.WAREHOUSE:  _FULL,
        ErpModule.INVENTORY:  _RAG_ONLY,
    },

    UserRole.PROCUREMENT_MANAGER: {
        ErpModule.PROCUREMENT: _FULL,
        ErpModule.INVENTORY:   _FULL,
        ErpModule.FINANCE:     _RAG_ONLY,
        ErpModule.REPORTING:   _RAG_ONLY,
    },

    UserRole.CRM_AGENT: {
        ErpModule.CRM:       _FULL,
        ErpModule.REPORTING: _RAG_ONLY,
    },

    UserRole.LOGISTICS_AGENT: {
        ErpModule.LOGISTICS:  _FULL,
        ErpModule.WAREHOUSE:  _FULL,
        ErpModule.REPORTING:  _RAG_ONLY,
    },

    # REPORTING_ANALYST: RAG access on all modules, zero SQL
    UserRole.REPORTING_ANALYST: {m: _RAG_ONLY for m in ErpModule},
}


# ---------------------------------------------------------------------------
# Table → module mapping (§ 8.4)
# ---------------------------------------------------------------------------

_TABLE_MODULE_MAP: dict[str, ErpModule] = {
    # INVENTORY
    "inventory":         ErpModule.INVENTORY,
    "products":          ErpModule.INVENTORY,
    "returns":           ErpModule.INVENTORY,
    "production_batches": ErpModule.INVENTORY,
    "quality_checks":    ErpModule.INVENTORY,
    # FINANCE
    "invoices":           ErpModule.FINANCE,
    "accounts_receivable": ErpModule.FINANCE,
    "vat_transactions":   ErpModule.FINANCE,
    "budget_actuals":     ErpModule.FINANCE,
    "payroll":            ErpModule.FINANCE,
    "assets":             ErpModule.FINANCE,
    "sales_orders":       ErpModule.FINANCE,
    # WAREHOUSE
    "warehouses":         ErpModule.WAREHOUSE,
    "bins":               ErpModule.WAREHOUSE,
    # PROCUREMENT
    "purchase_orders":    ErpModule.PROCUREMENT,
    "suppliers":          ErpModule.PROCUREMENT,
    "contracts":          ErpModule.PROCUREMENT,
    # CRM
    "customers":          ErpModule.CRM,
    "crm_interactions":   ErpModule.CRM,
    # LOGISTICS
    "shipments":          ErpModule.LOGISTICS,
    "delivery_routes":    ErpModule.LOGISTICS,
    # ADMIN
    "employees":          ErpModule.ADMIN,
    "users":              ErpModule.ADMIN,
    "leave_balances":     ErpModule.ADMIN,
}


# ---------------------------------------------------------------------------
# RAG collection → module mapping
# ---------------------------------------------------------------------------

_COLLECTION_MODULE_MAP: dict[str, ErpModule] = {
    # Named by module
    "inventory_docs":   ErpModule.INVENTORY,
    "finance_docs":     ErpModule.FINANCE,
    "warehouse_docs":   ErpModule.WAREHOUSE,
    "procurement_docs": ErpModule.PROCUREMENT,
    "crm_docs":         ErpModule.CRM,
    "logistics_docs":   ErpModule.LOGISTICS,
    "reporting_docs":   ErpModule.REPORTING,
    "admin_docs":       ErpModule.ADMIN,
    # Named by document type (ChunkStrategy)
    "sop_collection":   ErpModule.ADMIN,     # SOPs → operational / admin
    "bpmn_collection":  ErpModule.ADMIN,     # process models → admin
    "tax_collection":   ErpModule.FINANCE,   # DGI tax circulars → finance
}


def _resolve_collection_module(collection_name: str) -> Optional[ErpModule]:
    """Resolve a RAG collection name to its ErpModule.

    Tries exact match first, then falls back to substring matching on
    module values (e.g. collection ``"finance_2024"`` → ErpModule.FINANCE).
    Returns None if the collection cannot be mapped.
    """
    if collection_name in _COLLECTION_MODULE_MAP:
        return _COLLECTION_MODULE_MAP[collection_name]
    lower = collection_name.lower()
    for module in ErpModule:
        if module.value in lower:
            return module
    return None


def _parse_role(role: str) -> Optional[UserRole]:
    """Convert a raw role string from JWT claims to UserRole.

    Returns None for unknown role strings (results in no access).
    """
    try:
        return UserRole(role)
    except ValueError:
        logger.warning("rbac_policy.unknown_role", role=role)
        return None


# ---------------------------------------------------------------------------
# Public policy functions
# ---------------------------------------------------------------------------

def get_allowed_modules(role: str) -> dict[ErpModule, ModulePermission]:
    """Return the module permission map for the given role string.

    Args:
        role: Raw role string from ``request.state.role`` (JWT claim).

    Returns:
        Dict mapping ErpModule → ModulePermission for this role.
        An absent key means the role has no access to that module at all.
        Returns an empty dict for unknown roles.

    Examples::

        get_allowed_modules("SUPER_ADMIN")        # all 8 modules, _FULL
        get_allowed_modules("REPORTING_ANALYST")  # all 8 modules, _RAG_ONLY
        get_allowed_modules("FINANCE_MANAGER")    # FINANCE + REPORTING only
    """
    user_role = _parse_role(role)
    if user_role is None:
        return {}
    return dict(MODULE_ACCESS_MATRIX.get(user_role, {}))


def is_table_allowed(role: str, table_name: str) -> bool:
    """Return True if *role* may run SQL queries against *table_name*.

    Args:
        role:       Raw role string from JWT.
        table_name: Exact SQL table name (e.g. ``"invoices"``).

    Returns:
        True  — role has ``can_sql=True`` for the table's module.
        False — role lacks SQL permission, table is unknown, or role is invalid.

    Note:
        REPORTING_ANALYST always returns False (can_sql=False on every module).
        SUPER_ADMIN always returns True for any known table.
    """
    module = _TABLE_MODULE_MAP.get(table_name)
    if module is None:
        logger.warning("rbac_policy.unknown_table", table=table_name, role=role)
        return False

    permissions = get_allowed_modules(role)
    perm = permissions.get(module)
    allowed = perm is not None and perm.can_sql

    if not allowed:
        logger.info(
            "rbac_policy.table_denied",
            role=role,
            table=table_name,
            module=module.value,
        )
    return allowed


def is_collection_allowed(role: str, collection_name: str) -> bool:
    """Return True if *role* may query the RAG collection *collection_name*.

    Args:
        role:            Raw role string from JWT.
        collection_name: Milvus / MongoDB collection name.

    Returns:
        True  — role has ``can_rag=True`` for the collection's module.
        False — role lacks RAG permission or collection cannot be resolved.

    Note:
        SUPER_ADMIN returns True for any resolvable collection.
        REPORTING_ANALYST returns True for all collections (RAG-only role).
        Unknown collections are denied for all roles except SUPER_ADMIN.
    """
    module = _resolve_collection_module(collection_name)
    if module is None:
        # Unknown collection: only SUPER_ADMIN gets through
        user_role = _parse_role(role)
        allowed = user_role == UserRole.SUPER_ADMIN
        if not allowed:
            logger.warning(
                "rbac_policy.unknown_collection",
                collection=collection_name,
                role=role,
            )
        return allowed

    permissions = get_allowed_modules(role)
    perm = permissions.get(module)
    allowed = perm is not None and perm.can_rag

    if not allowed:
        logger.info(
            "rbac_policy.collection_denied",
            role=role,
            collection=collection_name,
            module=module.value,
        )
    return allowed


__all__ = [
    "ModulePermission",
    "MODULE_ACCESS_MATRIX",
    "get_allowed_modules",
    "is_table_allowed",
    "is_collection_allowed",
]
