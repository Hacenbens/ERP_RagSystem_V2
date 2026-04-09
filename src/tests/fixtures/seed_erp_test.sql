-- seed_erp_test.sql — Sprint 4
-- Seeds the erp_test PostgreSQL database for integration testing.
-- Run once before integration tests: psql -U erp_readonly -d erp_test -f seed_erp_test.sql
-- All data is scoped to test tenants: FERZA and ACME

-- ============================================================
-- Schema setup
-- ============================================================

CREATE TABLE IF NOT EXISTS sales_orders (
    order_id    TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    amount      NUMERIC(15, 2),
    status      TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS invoices (
    invoice_id  TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    supplier_id TEXT,
    amount      NUMERIC(15, 2),
    due_date    DATE,
    status      TEXT
);

CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    name        TEXT,
    status      TEXT
);

CREATE TABLE IF NOT EXISTS inventory (
    product_id  TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    warehouse_id TEXT,
    stock       INTEGER,
    reorder_level INTEGER
);

CREATE TABLE IF NOT EXISTS employees (
    employee_id TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    name        TEXT,
    department  TEXT,
    status      TEXT
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id       TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    amount      NUMERIC(15, 2),
    status      TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payroll (
    payroll_id  TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    period      TEXT,
    amount      NUMERIC(15, 2)
);

CREATE TABLE IF NOT EXISTS leave_balances (
    employee_id TEXT,
    tenant_id   TEXT NOT NULL,
    leave_days  INTEGER,
    PRIMARY KEY (employee_id, tenant_id)
);

CREATE TABLE IF NOT EXISTS vat_transactions (
    vat_id      TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    amount      NUMERIC(15, 2),
    period      TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS shipments (
    shipment_id     TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    expected_date   DATE,
    delivery_date   DATE,
    status          TEXT
);

-- ============================================================
-- Seed data — tenant FERZA
-- ============================================================

INSERT INTO sales_orders VALUES
    ('SO-F001', 'FERZA', 120000.00, 'open',    NOW() - INTERVAL '5 days'),
    ('SO-F002', 'FERZA', 85000.00,  'pending', NOW() - INTERVAL '10 days'),
    ('SO-F003', 'FERZA', 230000.00, 'closed',  NOW() - INTERVAL '20 days')
ON CONFLICT DO NOTHING;

INSERT INTO employees VALUES
    ('EMP-F001', 'FERZA', 'Amina Benali',   'Finance',    'active'),
    ('EMP-F002', 'FERZA', 'Karim Meziani',  'HR',         'active'),
    ('EMP-F003', 'FERZA', 'Riad Hamidi',    'Operations', 'active')
ON CONFLICT DO NOTHING;

INSERT INTO inventory VALUES
    ('SKU-F001', 'FERZA', 'WH-001', 200, 50),
    ('SKU-F002', 'FERZA', 'WH-001', 30,  50),
    ('SKU-F003', 'FERZA', 'WH-002', 500, 100)
ON CONFLICT DO NOTHING;

INSERT INTO vat_transactions VALUES
    ('VAT-F001', 'FERZA', 55000.00,  'Q1-2025', NOW() - INTERVAL '90 days'),
    ('VAT-F002', 'FERZA', 72000.00,  'Q1-2025', NOW() - INTERVAL '60 days')
ON CONFLICT DO NOTHING;

-- ============================================================
-- Seed data — tenant ACME
-- ============================================================

INSERT INTO sales_orders VALUES
    ('SO-A001', 'ACME', 95000.00,  'open',    NOW() - INTERVAL '3 days'),
    ('SO-A002', 'ACME', 145000.00, 'open',    NOW() - INTERVAL '7 days'),
    ('SO-A003', 'ACME', 60000.00,  'pending', NOW() - INTERVAL '15 days')
ON CONFLICT DO NOTHING;

INSERT INTO employees VALUES
    ('EMP-A001', 'ACME', 'Sarah Malik',    'Finance',  'active'),
    ('EMP-A002', 'ACME', 'David Chen',     'IT',       'active')
ON CONFLICT DO NOTHING;

INSERT INTO shipments VALUES
    ('SHP-A001', 'ACME', CURRENT_DATE - 5,  CURRENT_DATE - 2, 'delivered'),
    ('SHP-A002', 'ACME', CURRENT_DATE - 3,  NULL,             'delayed'),
    ('SHP-A003', 'ACME', CURRENT_DATE + 2,  NULL,             'in_transit')
ON CONFLICT DO NOTHING;
