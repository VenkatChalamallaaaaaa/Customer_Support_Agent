CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS refunds (
    refund_id          SERIAL PRIMARY KEY,
    order_id           TEXT NOT NULL,
    customer_unique_id TEXT NOT NULL,
    amount             NUMERIC(10,2) NOT NULL CHECK (amount > 0),
    reason             TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'pending_approval'
                       CHECK (status IN ('approved','pending_approval','declined')),
    decided_by         TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'agent_support') THEN
        CREATE ROLE agent_support LOGIN PASSWORD 'support_pw';
    END IF;
END $$;

GRANT CONNECT ON DATABASE olist TO agent_support;
GRANT USAGE ON SCHEMA public TO agent_support;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_support;
GRANT INSERT ON refunds TO agent_support;
GRANT USAGE ON SEQUENCE refunds_refund_id_seq TO agent_support;
ALTER ROLE agent_support SET statement_timeout = '10s';