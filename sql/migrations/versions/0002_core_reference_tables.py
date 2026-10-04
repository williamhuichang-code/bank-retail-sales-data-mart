"""core reference tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op


revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION core.std_cust_id(raw_id text) RETURNS text
        LANGUAGE sql IMMUTABLE AS $$
            -- legacy system drops a leading '00': 10 digits = keep, 8 digits = add '00', else NULL (never guessed)
            SELECT CASE
                     WHEN trim(raw_id) !~ '^[0-9]+$' THEN NULL
                     WHEN length(trim(raw_id)) = 10  THEN trim(raw_id)
                     WHEN length(trim(raw_id)) = 8   THEN '00' || trim(raw_id)
                   END
        $$;
    """)
    op.execute("""
        CREATE TABLE core.branch (
            branch_code text PRIMARY KEY CHECK (branch_code ~ '^B[0-9]{2}$')
        );
    """)
    op.execute("""
        CREATE TABLE core.branch_history (
            branch_code           text NOT NULL REFERENCES core.branch,
            effective_date        date NOT NULL,
            branch_name           text NOT NULL,
            region                text NOT NULL,
            branch_status         text NOT NULL CHECK (branch_status IN ('Active', 'Closed')),
            successor_branch_code text REFERENCES core.branch,
            PRIMARY KEY (branch_code, effective_date),
            CHECK ((branch_status = 'Closed') = (successor_branch_code IS NOT NULL))
        );
    """)
    op.execute("""
        CREATE TABLE core.product (
            product_code       text PRIMARY KEY CHECK (product_code ~ '^P[0-9]{2}$'),
            product_name       text NOT NULL,
            product_category   text NOT NULL,
            product_risk_level text NOT NULL CHECK (product_risk_level ~ '^R[1-5]$'),
            fee_rate           numeric(6,4) NOT NULL CHECK (fee_rate >= 0)
        );
    """)
    op.execute("""
        CREATE TABLE core.customer (
            cust_id        text PRIMARY KEY CHECK (cust_id ~ '^[0-9]{10}$'),
            cust_id_legacy text NOT NULL,
            cust_name      text NOT NULL,
            cust_dob       date NOT NULL,
            cust_gender    text NOT NULL CHECK (cust_gender IN ('M', 'F')),
            CHECK (core.std_cust_id(cust_id_legacy) = cust_id)
        );
    """)
    op.execute("""
        CREATE TABLE core.customer_history (
            cust_id           text NOT NULL REFERENCES core.customer,
            effective_date    date NOT NULL,
            cust_segment      text NOT NULL CHECK (cust_segment IN ('Mass', 'Affluent', 'Private')),
            cust_risk_profile text NOT NULL CHECK (cust_risk_profile ~ '^R[1-5]$'),
            change_reason     text,
            PRIMARY KEY (cust_id, effective_date)
        );
    """)
    op.execute("""
        CREATE TABLE core.fx_rate (
            currency_code text NOT NULL CHECK (currency_code ~ '^[A-Z]{3}$'),
            rate_date     date NOT NULL,
            units_per_usd numeric(12,6) NOT NULL CHECK (units_per_usd > 0),
            PRIMARY KEY (currency_code, rate_date)
        );
    """)
    op.execute("""
        CREATE TABLE core.sales_person (
            sales_person_id   text PRIMARY KEY CHECK (sales_person_id ~ '^E[0-9]{3}$'),
            sales_person_name text NOT NULL
        );
    """)
    op.execute("""
        CREATE TABLE core.sales_person_confirmation (
            txn_id         text PRIMARY KEY REFERENCES raw.sales_log,
            action         text CHECK (action IN ('Acknowledged', 'Corrected')),
            confirmed_id   text REFERENCES core.sales_person,
            confirmed_by   text,
            confirmed_date date,
            -- pending (all empty) or fully confirmed (all filled): nothing in between
            CHECK (   (action IS NULL AND confirmed_id IS NULL AND confirmed_by IS NULL AND confirmed_date IS NULL)
                   OR (action IS NOT NULL AND confirmed_id IS NOT NULL AND confirmed_by IS NOT NULL AND confirmed_date IS NOT NULL))
        );
    """)

def downgrade() -> None:
    op.execute("""DROP TABLE core.sales_person_confirmation;""")
    op.execute("""DROP TABLE core.sales_person;""")
    op.execute("""DROP TABLE core.fx_rate;""")
    op.execute("""DROP TABLE core.customer_history;""")
    op.execute("""DROP TABLE core.customer;""")
    op.execute("""DROP TABLE core.product;""")
    op.execute("""DROP TABLE core.branch_history;""")
    op.execute("""DROP TABLE core.branch;""")
    op.execute("""DROP FUNCTION core.std_cust_id(text);""")
