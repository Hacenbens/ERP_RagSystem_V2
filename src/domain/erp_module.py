"""
ErpModule — ERP business domain enum.

Source of truth: erp_rag_claude_code/docs/source_of_truth.md § 8.4

Used as:
- Keys in MODULE_ACCESS_MATRIX (src/infrastructure/auth/erp_rbac_policy.py)
- The ``module`` label on RBAC violation Prometheus metrics
- The grouping unit for SQL table and RAG collection access control

Typical SQL tables per module
──────────────────────────────
INVENTORY   → inventory, products, returns, production_batches, quality_checks
FINANCE     → invoices, accounts_receivable, vat_transactions, budget_actuals,
               payroll, assets, sales_orders
WAREHOUSE   → warehouses, bins
PROCUREMENT → purchase_orders, suppliers, contracts
CRM         → customers, crm_interactions
LOGISTICS   → shipments, delivery_routes
REPORTING   → budget_actuals (cross-module aggregates, read via FINANCE)
ADMIN       → employees, users, leave_balances
"""
from __future__ import annotations

from enum import Enum


class ErpModule(str, Enum):
    """Eight ERP business domains used for module-level RBAC."""

    INVENTORY   = "inventory"
    FINANCE     = "finance"
    WAREHOUSE   = "warehouse"
    PROCUREMENT = "procurement"
    CRM         = "crm"
    LOGISTICS   = "logistics"
    REPORTING   = "reporting"
    ADMIN       = "admin"


__all__ = ["ErpModule"]
