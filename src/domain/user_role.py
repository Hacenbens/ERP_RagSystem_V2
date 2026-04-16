"""
UserRole — canonical ERP persona enum.

Source of truth: erp_rag_claude_code/docs/source_of_truth.md § 8.1

Rules:
- SUPER_ADMIN is the only role permitted on /admin/* routes.
- REPORTING_ANALYST has RAG access only — SQL is always denied.
- All other roles have SQL + RAG on their permitted modules
  (see MODULE_ACCESS_MATRIX in src/infrastructure/auth/erp_rbac_policy.py).
- Never hard-code role strings — always import this enum.

Migration from placeholder roles:
  "ADMIN"   → UserRole.SUPER_ADMIN
  "MANAGER" → UserRole.PRODUCT_MANAGER
  "ANALYST" → UserRole.REPORTING_ANALYST
  "VIEWER"  → UserRole.REPORTING_ANALYST
"""
from __future__ import annotations

from enum import Enum


class UserRole(str, Enum):
    """Nine ERP personas that a JWT may carry."""

    SUPER_ADMIN         = "SUPER_ADMIN"
    PRODUCT_MANAGER     = "PRODUCT_MANAGER"
    INVENTORY_MANAGER   = "INVENTORY_MANAGER"
    FINANCE_MANAGER     = "FINANCE_MANAGER"
    WAREHOUSE_OPERATOR  = "WAREHOUSE_OPERATOR"
    PROCUREMENT_MANAGER = "PROCUREMENT_MANAGER"
    CRM_AGENT           = "CRM_AGENT"
    LOGISTICS_AGENT     = "LOGISTICS_AGENT"
    REPORTING_ANALYST   = "REPORTING_ANALYST"


__all__ = ["UserRole"]
