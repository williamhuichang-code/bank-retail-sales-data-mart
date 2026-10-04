-- 001_setup_db.sql
-- One-time bootstrap: bank_sales database, its schemas and the etl role's rights.
-- Run once with psql as the admin user. Tables and views are managed by Alembic.
-- Assumes the cluster-wide role `etl` already exists (created by homelab-postgres/activitywatch).

\set ON_ERROR_STOP on

CREATE DATABASE bank_sales;
REVOKE CONNECT ON DATABASE bank_sales FROM PUBLIC;
GRANT  CONNECT ON DATABASE bank_sales TO etl;

\connect bank_sales

CREATE SCHEMA raw;    -- landing layer: sales exactly as captured
CREATE SCHEMA core;   -- 3NF reference tables + clean transaction view
CREATE SCHEMA mart;   -- one big table (OBT) + report views
CREATE SCHEMA dq;     -- data-quality checks

-- etl may only ADD sales to raw: no UPDATE, DELETE or TRUNCATE.
-- This enforces the non-volatile property by permission, not by discipline.
GRANT USAGE ON SCHEMA raw TO etl;
ALTER DEFAULT PRIVILEGES IN SCHEMA raw GRANT SELECT, INSERT ON TABLES TO etl;
