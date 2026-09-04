-- ERP replica fixture for local testing.
--
-- Every table carries tenant_id: QueryValidator rejects any statement without
-- a WHERE tenant_id filter, so a table without the column could never be
-- queried by this system at all.
--
-- Table names match _TABLE_MAP in src/infrastructure/erp/query_generator.py.
-- Columns match what _offline_generate emits: amount for SUM(amount),
-- created_at for DATE_TRUNC month grouping, due_date for the overdue filter,
-- status for pending/active, department for GROUP BY department.
--
-- Two tenants are seeded so cross-tenant leakage is visible rather than
-- theoretical: 'ferza' has four rows per table, 'acme' has two different ones.

BEGIN;


CREATE TABLE IF NOT EXISTS sales_orders (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    order_no     TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_sales_orders_tenant ON sales_orders (tenant_id);
INSERT INTO sales_orders (tenant_id, order_no, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'SO-1001', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'SO-1002', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'SO-1003', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'SO-1004', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'SO-1001', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'SO-1002', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS invoices (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    invoice_no   TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_invoices_tenant ON invoices (tenant_id);
INSERT INTO invoices (tenant_id, invoice_no, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'INV-2201', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'INV-2202', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'INV-2203', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'INV-2204', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'INV-2201', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'INV-2202', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    po_no        TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_tenant ON purchase_orders (tenant_id);
INSERT INTO purchase_orders (tenant_id, po_no, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'PO-3301', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'PO-3302', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'PO-3303', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'PO-3304', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'PO-3301', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'PO-3302', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS suppliers (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    name         TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_suppliers_tenant ON suppliers (tenant_id);
INSERT INTO suppliers (tenant_id, name, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'Sonelgaz Industrie', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'ETS Boukhari', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'Cevital Agro', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'SARL Medtech', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'Sonelgaz Industrie', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'ETS Boukhari', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS customers (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    name         TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_customers_tenant ON customers (tenant_id);
INSERT INTO customers (tenant_id, name, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'Naftal SPA', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'Groupe Benamor', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'Condor Electronics', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'Hôpital Mustapha', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'Naftal SPA', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'Groupe Benamor', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS employees (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    full_name    TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_employees_tenant ON employees (tenant_id);
INSERT INTO employees (tenant_id, full_name, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'Amina Kaci', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'Yacine Belkacem', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'Nadia Hamdi', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'Karim Zerrouki', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'Amina Kaci', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'Yacine Belkacem', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS inventory (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    sku          TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_inventory_tenant ON inventory (tenant_id);
INSERT INTO inventory (tenant_id, sku, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'SKU-VLV-01', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'SKU-PMP-02', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'SKU-CBL-03', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'SKU-FLT-04', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'SKU-VLV-01', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'SKU-PMP-02', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS products (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    sku          TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_products_tenant ON products (tenant_id);
INSERT INTO products (tenant_id, sku, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'SKU-VLV-01', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'SKU-PMP-02', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'SKU-CBL-03', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'SKU-FLT-04', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'SKU-VLV-01', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'SKU-PMP-02', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS accounts_receivable (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    reference    TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_accounts_receivable_tenant ON accounts_receivable (tenant_id);
INSERT INTO accounts_receivable (tenant_id, reference, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'AR-501', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'AR-502', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'AR-503', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'AR-504', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'AR-501', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'AR-502', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS contracts (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    reference    TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_contracts_tenant ON contracts (tenant_id);
INSERT INTO contracts (tenant_id, reference, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'CTR-77', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'CTR-78', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'CTR-79', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'CTR-80', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'CTR-77', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'CTR-78', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS payroll (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    period       TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_payroll_tenant ON payroll (tenant_id);
INSERT INTO payroll (tenant_id, period, amount, status, department, created_at, due_date) VALUES
    ('ferza', '2026-06', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', '2026-07', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', '2026-08', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', '2026-09', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', '2026-06', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', '2026-07', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS quality_checks (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    reference    TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_quality_checks_tenant ON quality_checks (tenant_id);
INSERT INTO quality_checks (tenant_id, reference, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'QC-11', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'QC-12', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'QC-13', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'QC-14', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'QC-11', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'QC-12', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS vat_transactions (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    reference    TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_vat_transactions_tenant ON vat_transactions (tenant_id);
INSERT INTO vat_transactions (tenant_id, reference, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'VAT-901', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'VAT-902', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'VAT-903', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'VAT-904', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'VAT-901', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'VAT-902', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS assets (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    asset_tag    TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_assets_tenant ON assets (tenant_id);
INSERT INTO assets (tenant_id, asset_tag, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'AST-01', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'AST-02', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'AST-03', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'AST-04', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'AST-01', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'AST-02', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS production_batches (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    batch_no     TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_production_batches_tenant ON production_batches (tenant_id);
INSERT INTO production_batches (tenant_id, batch_no, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'BATCH-A1', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'BATCH-A2', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'BATCH-B1', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'BATCH-B2', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'BATCH-A1', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'BATCH-A2', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS returns (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    reference    TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_returns_tenant ON returns (tenant_id);
INSERT INTO returns (tenant_id, reference, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'RET-21', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'RET-22', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'RET-23', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'RET-24', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'RET-21', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'RET-22', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS budget_actuals (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    cost_centre  TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_budget_actuals_tenant ON budget_actuals (tenant_id);
INSERT INTO budget_actuals (tenant_id, cost_centre, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'CC-FIN', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'CC-OPS', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'CC-LOG', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'CC-HR', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'CC-FIN', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'CC-OPS', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS shipments (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    tracking_no  TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_shipments_tenant ON shipments (tenant_id);
INSERT INTO shipments (tenant_id, tracking_no, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'SHP-441', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'SHP-442', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'SHP-443', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'SHP-444', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'SHP-441', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'SHP-442', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

CREATE TABLE IF NOT EXISTS leave_balances (
    id           SERIAL PRIMARY KEY,
    tenant_id    TEXT           NOT NULL,
    employee_ref TEXT           NOT NULL,
    amount       NUMERIC(14,2)  NOT NULL DEFAULT 0,
    status       TEXT           NOT NULL,
    department   TEXT,
    created_at   TIMESTAMPTZ    NOT NULL DEFAULT now(),
    due_date     DATE
);
CREATE INDEX IF NOT EXISTS idx_leave_balances_tenant ON leave_balances (tenant_id);
INSERT INTO leave_balances (tenant_id, employee_ref, amount, status, department, created_at, due_date) VALUES
    ('ferza', 'EMP-01', 125000.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -20),
    ('ferza', 'EMP-02', 487500.50, 'pending', 'Operations', now() - interval '37 days', CURRENT_DATE + -5),
    ('ferza', 'EMP-03', 92300.75, 'active', 'Logistics', now() - interval '74 days', CURRENT_DATE + 10),
    ('ferza', 'EMP-04', 1250000.00, 'closed', 'HR', now() - interval '111 days', CURRENT_DATE + 25),
    ('acme', 'EMP-01', 62500.00, 'open', 'Finance', now() - interval '0 days', CURRENT_DATE + -5),
    ('acme', 'EMP-02', 243750.25, 'pending', 'Operations', now() - interval '11 days', CURRENT_DATE + 4);

-- Read-only role. The SQL validator already blocks writes and DDL, but
-- database permissions are the layer that does not depend on the application
-- being correct.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'erp_readonly') THEN
        CREATE ROLE erp_readonly LOGIN PASSWORD 'erp_ro_dev_pw_2026';
    END IF;
END $$;

GRANT CONNECT ON DATABASE erp_prod TO erp_readonly;
GRANT USAGE ON SCHEMA public TO erp_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO erp_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO erp_readonly;

COMMIT;
