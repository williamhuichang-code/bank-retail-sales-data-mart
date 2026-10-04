"""mart: one big table (OBT)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op


revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE VIEW mart.sales_obt AS
        SELECT t.txn_id, t.txn_date_time, t.txn_date, tm.time AS txn_time,
               d.year, d.quarter, d.month, d.iso_week, d.weekday, tm.day_part,
               t.branch_code, b.effective_date AS branch_info_since, b.branch_name, b.region, b.branch_status,
               t.product_code, p.product_name, p.product_category, p.product_risk_level, p.fee_rate,
               t.cust_id, c.cust_name, c.cust_dob,
               extract(year FROM age(t.txn_date, c.cust_dob))::int AS cust_age_at_sale,
               c.cust_gender,
               h.effective_date AS cust_info_since, h.cust_segment, h.cust_risk_profile,
               t.channel, t.campaign_code,
               t.currency, fx.rate_date AS fx_rate_date,
               hk.units_per_usd / fx.units_per_usd                 AS fx_rate_to_hkd,
               t.amount_local,
               t.amount_local * hk.units_per_usd / fx.units_per_usd AS amount_hkd,
               t.sales_person_id_typed, t.sales_person_id_std, t.sales_person_check,
               t.sales_person_id_corrected, sp.sales_person_name,
               t.status
        FROM core.sales_transaction t
        LEFT JOIN core.ref_date d  ON d.date = t.txn_date
        LEFT JOIN core.ref_time tm ON tm.time_key = t.time_key
        -- as-of lookups: the latest version on or before the sale date
        LEFT JOIN LATERAL (
            SELECT * FROM core.branch_history b
            WHERE b.branch_code = t.branch_code AND b.effective_date <= t.txn_date
            ORDER BY b.effective_date DESC LIMIT 1) b ON true
        LEFT JOIN core.product p   ON p.product_code = t.product_code
        LEFT JOIN core.customer c  ON c.cust_id = t.cust_id
        LEFT JOIN LATERAL (
            SELECT * FROM core.customer_history h
            WHERE h.cust_id = t.cust_id AND h.effective_date <= t.txn_date
            ORDER BY h.effective_date DESC LIMIT 1) h ON true
        LEFT JOIN LATERAL (
            SELECT * FROM core.fx_rate f
            WHERE f.currency_code = t.currency AND f.rate_date <= t.txn_date
            ORDER BY f.rate_date DESC LIMIT 1) fx ON true
        LEFT JOIN core.fx_rate hk  ON hk.currency_code = 'HKD' AND hk.rate_date = fx.rate_date
        LEFT JOIN core.sales_person sp ON sp.sales_person_id = t.sales_person_id_corrected;
    """)

def downgrade() -> None:
    op.execute("""DROP VIEW mart.sales_obt;""")
