"""
Unit tests — erp_rbac_policy.py (Sprint 5, Task 2).

Covers:
  - get_allowed_modules: all 9 roles, unknown/empty inputs
  - is_table_allowed:    happy paths, denied paths, unknown tables
  - is_collection_allowed: exact match, substring match, unknown collection
  - Security invariants: REPORTING_ANALYST SQL denial, SUPER_ADMIN full access,
    matrix completeness, ModulePermission immutability

Source of truth: erp_rag_claude_code/docs/source_of_truth.md § 8.5
Naming: test_{function}_{scenario}_{expected_outcome}
"""
from __future__ import annotations

import pytest

from src.domain.erp_module import ErpModule
from src.domain.user_role import UserRole
from src.infrastructure.auth.erp_rbac_policy import (
    MODULE_ACCESS_MATRIX,
    ModulePermission,
    get_allowed_modules,
    is_collection_allowed,
    is_table_allowed,
)


# ===========================================================================
# get_allowed_modules
# ===========================================================================

class TestGetAllowedModulesSuperAdmin:
    """SUPER_ADMIN must receive all modules with full SQL + RAG access."""

    def test_super_admin_receives_all_eight_modules(self):
        result = get_allowed_modules("SUPER_ADMIN")
        assert set(result.keys()) == set(ErpModule)

    def test_super_admin_all_modules_have_sql_access(self):
        result = get_allowed_modules("SUPER_ADMIN")
        assert all(perm.can_sql for perm in result.values())

    def test_super_admin_all_modules_have_rag_access(self):
        result = get_allowed_modules("SUPER_ADMIN")
        assert all(perm.can_rag for perm in result.values())


class TestGetAllowedModulesReportingAnalyst:
    """REPORTING_ANALYST must receive all modules with RAG access only."""

    def test_reporting_analyst_receives_all_eight_modules(self):
        result = get_allowed_modules("REPORTING_ANALYST")
        assert set(result.keys()) == set(ErpModule)

    def test_reporting_analyst_no_module_has_sql_access(self):
        result = get_allowed_modules("REPORTING_ANALYST")
        assert not any(perm.can_sql for perm in result.values()), (
            "REPORTING_ANALYST must have can_sql=False on every module"
        )

    def test_reporting_analyst_all_modules_have_rag_access(self):
        result = get_allowed_modules("REPORTING_ANALYST")
        assert all(perm.can_rag for perm in result.values())


class TestGetAllowedModulesSpecificRoles:
    """Each role receives exactly the modules defined in MODULE_ACCESS_MATRIX."""

    def test_finance_manager_receives_finance_and_reporting_only(self):
        result = get_allowed_modules("FINANCE_MANAGER")
        assert set(result.keys()) == {ErpModule.FINANCE, ErpModule.REPORTING}

    def test_finance_manager_finance_module_has_full_access(self):
        result = get_allowed_modules("FINANCE_MANAGER")
        assert result[ErpModule.FINANCE].can_sql is True
        assert result[ErpModule.FINANCE].can_rag is True

    def test_product_manager_receives_inventory_procurement_crm_reporting(self):
        result = get_allowed_modules("PRODUCT_MANAGER")
        assert set(result.keys()) == {
            ErpModule.INVENTORY, ErpModule.PROCUREMENT,
            ErpModule.CRM, ErpModule.REPORTING,
        }

    def test_product_manager_reporting_is_rag_only(self):
        result = get_allowed_modules("PRODUCT_MANAGER")
        perm = result[ErpModule.REPORTING]
        assert perm.can_sql is False
        assert perm.can_rag is True

    def test_inventory_manager_receives_inventory_warehouse_reporting(self):
        result = get_allowed_modules("INVENTORY_MANAGER")
        assert set(result.keys()) == {
            ErpModule.INVENTORY, ErpModule.WAREHOUSE, ErpModule.REPORTING,
        }

    def test_warehouse_operator_inventory_is_rag_only(self):
        result = get_allowed_modules("WAREHOUSE_OPERATOR")
        assert result[ErpModule.WAREHOUSE].can_sql is True
        assert result[ErpModule.INVENTORY].can_sql is False
        assert result[ErpModule.INVENTORY].can_rag is True

    def test_procurement_manager_finance_is_rag_only(self):
        result = get_allowed_modules("PROCUREMENT_MANAGER")
        assert result[ErpModule.FINANCE].can_sql is False
        assert result[ErpModule.FINANCE].can_rag is True

    def test_crm_agent_receives_crm_and_reporting_only(self):
        result = get_allowed_modules("CRM_AGENT")
        assert set(result.keys()) == {ErpModule.CRM, ErpModule.REPORTING}

    def test_logistics_agent_receives_logistics_warehouse_reporting(self):
        result = get_allowed_modules("LOGISTICS_AGENT")
        assert set(result.keys()) == {
            ErpModule.LOGISTICS, ErpModule.WAREHOUSE, ErpModule.REPORTING,
        }

    def test_get_allowed_modules_returns_independent_copy(self):
        """Mutating the returned dict must not affect MODULE_ACCESS_MATRIX."""
        result = get_allowed_modules("FINANCE_MANAGER")
        original_size = len(MODULE_ACCESS_MATRIX[UserRole.FINANCE_MANAGER])
        result[ErpModule.CRM] = ModulePermission(can_sql=True, can_rag=True)
        assert len(MODULE_ACCESS_MATRIX[UserRole.FINANCE_MANAGER]) == original_size


class TestGetAllowedModulesFailurePaths:
    """Unknown or invalid role strings must return an empty dict."""

    def test_unknown_role_returns_empty_dict(self):
        assert get_allowed_modules("UNKNOWN_ROLE") == {}

    def test_empty_string_role_returns_empty_dict(self):
        assert get_allowed_modules("") == {}

    def test_old_placeholder_admin_returns_empty_dict(self):
        """Old 'ADMIN' string is not a valid UserRole since § 8.6 migration."""
        assert get_allowed_modules("ADMIN") == {}

    def test_old_placeholder_viewer_returns_empty_dict(self):
        assert get_allowed_modules("VIEWER") == {}

    def test_lowercase_role_returns_empty_dict(self):
        assert get_allowed_modules("super_admin") == {}


# ===========================================================================
# is_table_allowed
# ===========================================================================

class TestIsTableAllowedHappyPaths:
    """Roles with SQL access on a table's module must return True."""

    def test_super_admin_allowed_on_finance_table(self):
        assert is_table_allowed("SUPER_ADMIN", "invoices") is True

    def test_super_admin_allowed_on_inventory_table(self):
        assert is_table_allowed("SUPER_ADMIN", "inventory") is True

    def test_super_admin_allowed_on_every_known_table(self):
        known_tables = [
            "inventory", "products", "returns",
            "invoices", "payroll", "vat_transactions",
            "purchase_orders", "suppliers",
            "customers",
            "shipments",
            "employees",
        ]
        for table in known_tables:
            assert is_table_allowed("SUPER_ADMIN", table) is True, (
                f"SUPER_ADMIN should be allowed on table '{table}'"
            )

    def test_finance_manager_allowed_on_invoices(self):
        assert is_table_allowed("FINANCE_MANAGER", "invoices") is True

    def test_finance_manager_allowed_on_payroll(self):
        assert is_table_allowed("FINANCE_MANAGER", "payroll") is True

    def test_finance_manager_allowed_on_vat_transactions(self):
        assert is_table_allowed("FINANCE_MANAGER", "vat_transactions") is True

    def test_product_manager_allowed_on_inventory(self):
        assert is_table_allowed("PRODUCT_MANAGER", "inventory") is True

    def test_product_manager_allowed_on_customers(self):
        assert is_table_allowed("PRODUCT_MANAGER", "customers") is True

    def test_inventory_manager_allowed_on_products(self):
        assert is_table_allowed("INVENTORY_MANAGER", "products") is True

    def test_warehouse_operator_allowed_on_warehouses(self):
        assert is_table_allowed("WAREHOUSE_OPERATOR", "warehouses") is True

    def test_procurement_manager_allowed_on_purchase_orders(self):
        assert is_table_allowed("PROCUREMENT_MANAGER", "purchase_orders") is True

    def test_crm_agent_allowed_on_customers(self):
        assert is_table_allowed("CRM_AGENT", "customers") is True

    def test_logistics_agent_allowed_on_shipments(self):
        assert is_table_allowed("LOGISTICS_AGENT", "shipments") is True


class TestIsTableDeniedPaths:
    """Roles without SQL access on a module must return False."""

    @pytest.mark.parametrize("table", [
        "invoices", "inventory", "customers", "shipments",
        "purchase_orders", "employees",
    ])
    def test_reporting_analyst_denied_on_all_known_tables(self, table):
        assert is_table_allowed("REPORTING_ANALYST", table) is False, (
            f"REPORTING_ANALYST must be denied SQL on '{table}'"
        )

    def test_finance_manager_denied_on_crm_table(self):
        """FINANCE_MANAGER has no CRM module — customers is denied."""
        assert is_table_allowed("FINANCE_MANAGER", "customers") is False

    def test_finance_manager_denied_on_inventory_table(self):
        assert is_table_allowed("FINANCE_MANAGER", "inventory") is False

    def test_product_manager_denied_on_finance_table(self):
        """PRODUCT_MANAGER has no FINANCE module."""
        assert is_table_allowed("PRODUCT_MANAGER", "invoices") is False

    def test_product_manager_denied_on_payroll(self):
        assert is_table_allowed("PRODUCT_MANAGER", "payroll") is False

    def test_warehouse_operator_denied_on_inventory_table(self):
        """WAREHOUSE_OPERATOR has INVENTORY as RAG_ONLY — SQL must be denied."""
        assert is_table_allowed("WAREHOUSE_OPERATOR", "inventory") is False

    def test_warehouse_operator_denied_on_finance_table(self):
        assert is_table_allowed("WAREHOUSE_OPERATOR", "invoices") is False

    def test_crm_agent_denied_on_finance_table(self):
        assert is_table_allowed("CRM_AGENT", "payroll") is False

    def test_logistics_agent_denied_on_finance_table(self):
        assert is_table_allowed("LOGISTICS_AGENT", "invoices") is False

    def test_unknown_table_denied_for_super_admin(self):
        """Even SUPER_ADMIN cannot access an unregistered table."""
        assert is_table_allowed("SUPER_ADMIN", "ghost_table_xyz") is False

    def test_unknown_table_denied_for_any_role(self):
        assert is_table_allowed("FINANCE_MANAGER", "ghost_table_xyz") is False

    def test_empty_table_name_denied(self):
        assert is_table_allowed("SUPER_ADMIN", "") is False

    def test_empty_role_denied_on_known_table(self):
        assert is_table_allowed("", "invoices") is False

    def test_unknown_role_denied_on_known_table(self):
        assert is_table_allowed("HACKER_ROLE", "invoices") is False


# ===========================================================================
# is_collection_allowed
# ===========================================================================

class TestIsCollectionAllowedHappyPaths:
    """Roles with RAG access on a collection's module must return True."""

    def test_super_admin_allowed_on_finance_collection(self):
        assert is_collection_allowed("SUPER_ADMIN", "finance_docs") is True

    def test_super_admin_allowed_on_unknown_collection(self):
        """SUPER_ADMIN has unrestricted access — even unknown collections."""
        assert is_collection_allowed("SUPER_ADMIN", "totally_unknown_xyz") is True

    def test_reporting_analyst_allowed_on_finance_collection(self):
        """REPORTING_ANALYST is RAG-only — all collections are accessible."""
        assert is_collection_allowed("REPORTING_ANALYST", "finance_docs") is True

    def test_reporting_analyst_allowed_on_warehouse_collection(self):
        assert is_collection_allowed("REPORTING_ANALYST", "warehouse_docs") is True

    def test_finance_manager_allowed_on_finance_collection(self):
        assert is_collection_allowed("FINANCE_MANAGER", "finance_docs") is True

    def test_finance_manager_allowed_on_reporting_collection(self):
        assert is_collection_allowed("FINANCE_MANAGER", "reporting_docs") is True

    def test_finance_manager_allowed_on_tax_collection(self):
        """tax_collection maps to FINANCE via _COLLECTION_MODULE_MAP."""
        assert is_collection_allowed("FINANCE_MANAGER", "tax_collection") is True

    def test_finance_manager_allowed_on_substring_match_collection(self):
        """Collection name containing 'finance' resolves via substring fallback."""
        assert is_collection_allowed("FINANCE_MANAGER", "finance_2024_archive") is True

    def test_crm_agent_allowed_on_crm_collection(self):
        assert is_collection_allowed("CRM_AGENT", "crm_docs") is True

    def test_logistics_agent_allowed_on_logistics_collection(self):
        assert is_collection_allowed("LOGISTICS_AGENT", "logistics_docs") is True

    def test_logistics_agent_allowed_on_warehouse_collection(self):
        assert is_collection_allowed("LOGISTICS_AGENT", "warehouse_docs") is True

    def test_admin_collection_allowed_for_super_admin_via_sop(self):
        """sop_collection maps to ADMIN — SUPER_ADMIN can access it."""
        assert is_collection_allowed("SUPER_ADMIN", "sop_collection") is True


class TestIsCollectionDeniedPaths:
    """Roles without RAG access on a module must return False."""

    def test_warehouse_operator_denied_on_finance_collection(self):
        """WAREHOUSE_OPERATOR has no FINANCE module at all."""
        assert is_collection_allowed("WAREHOUSE_OPERATOR", "finance_docs") is False

    def test_finance_manager_denied_on_crm_collection(self):
        assert is_collection_allowed("FINANCE_MANAGER", "crm_docs") is False

    def test_product_manager_denied_on_finance_collection(self):
        assert is_collection_allowed("PRODUCT_MANAGER", "finance_docs") is False

    def test_crm_agent_denied_on_warehouse_collection(self):
        assert is_collection_allowed("CRM_AGENT", "warehouse_docs") is False

    def test_logistics_agent_denied_on_unknown_collection(self):
        """Unknown collection → only SUPER_ADMIN passes."""
        assert is_collection_allowed("LOGISTICS_AGENT", "totally_unknown_xyz") is False

    def test_empty_role_denied_on_known_collection(self):
        assert is_collection_allowed("", "finance_docs") is False

    def test_unknown_role_denied_on_known_collection(self):
        assert is_collection_allowed("BAD_ACTOR", "finance_docs") is False


# ===========================================================================
# Security invariants (critical)
# ===========================================================================

class TestSecurityInvariants:
    """Non-negotiable security properties that must hold across all roles."""

    def test_module_access_matrix_covers_all_user_roles(self):
        """Every UserRole must have an entry in MODULE_ACCESS_MATRIX."""
        for role in UserRole:
            assert role in MODULE_ACCESS_MATRIX, (
                f"UserRole.{role.name} missing from MODULE_ACCESS_MATRIX"
            )

    def test_module_permission_is_immutable(self):
        """ModulePermission is a frozen dataclass — mutation must raise."""
        perm = ModulePermission(can_sql=True, can_rag=True)
        with pytest.raises((AttributeError, TypeError)):
            perm.can_sql = False  # type: ignore[misc]

    def test_reporting_analyst_sql_denied_across_all_finance_tables(self):
        """Critical: REPORTING_ANALYST must never access finance schema via SQL."""
        finance_tables = [
            "invoices", "accounts_receivable", "vat_transactions",
            "budget_actuals", "payroll", "assets", "sales_orders",
        ]
        for table in finance_tables:
            assert is_table_allowed("REPORTING_ANALYST", table) is False, (
                f"REPORTING_ANALYST must not have SQL access to finance table '{table}'"
            )

    def test_super_admin_sql_granted_across_all_known_tables(self):
        """SUPER_ADMIN must have SQL access to every registered table."""
        all_tables = [
            # INVENTORY
            "inventory", "products", "returns", "production_batches", "quality_checks",
            # FINANCE
            "invoices", "accounts_receivable", "vat_transactions",
            "budget_actuals", "payroll", "assets", "sales_orders",
            # WAREHOUSE
            "warehouses", "bins",
            # PROCUREMENT
            "purchase_orders", "suppliers", "contracts",
            # CRM
            "customers", "crm_interactions",
            # LOGISTICS
            "shipments", "delivery_routes",
            # ADMIN
            "employees", "users", "leave_balances",
        ]
        for table in all_tables:
            assert is_table_allowed("SUPER_ADMIN", table) is True, (
                f"SUPER_ADMIN must have SQL access to '{table}'"
            )

    def test_no_role_escalation_warehouse_to_finance(self):
        """WAREHOUSE_OPERATOR must not access FINANCE tables at any point."""
        finance_tables = ["invoices", "payroll", "vat_transactions", "budget_actuals"]
        for table in finance_tables:
            assert is_table_allowed("WAREHOUSE_OPERATOR", table) is False

    def test_no_role_escalation_crm_to_finance(self):
        """CRM_AGENT must not access FINANCE tables."""
        assert is_table_allowed("CRM_AGENT", "invoices") is False
        assert is_table_allowed("CRM_AGENT", "payroll") is False

    def test_get_allowed_modules_never_returns_none(self):
        """get_allowed_modules must always return a dict, never None."""
        for role in list(UserRole) + ["UNKNOWN", ""]:
            result = get_allowed_modules(role.value if isinstance(role, UserRole) else role)
            assert result is not None
            assert isinstance(result, dict)
