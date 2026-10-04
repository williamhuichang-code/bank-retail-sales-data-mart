"""core views: calendar, time, current views, clean transactions

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op


revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE VIEW core.ref_date AS
        SELECT d::date                              AS date,
               extract(year FROM d)::int            AS year,
               'Q' || extract(quarter FROM d)::int  AS quarter,
               extract(month FROM d)::int           AS month,
               extract(week FROM d)::int            AS iso_week,
               to_char(d, 'Dy')                     AS weekday
        FROM generate_series((SELECT min(txn_date_time)::date FROM raw.sales_log),
                             (SELECT max(txn_date_time)::date FROM raw.sales_log),
                             interval '1 day') AS d;
    """)
    op.execute("""
        CREATE VIEW core.ref_time AS
        SELECT m                                AS time_key,
               make_time(m / 60, m % 60, 0)     AS time,
               m / 60                           AS hour,
               CASE WHEN m / 60 < 6  THEN 'Night'
                    WHEN m / 60 < 12 THEN 'Morning'
                    WHEN m / 60 < 18 THEN 'Afternoon'
                    WHEN m / 60 < 22 THEN 'Evening'
                    ELSE 'Night' END            AS day_part
        FROM generate_series(0, 1439) AS m;
    """)
    op.execute("""
        CREATE VIEW core.branch_current AS
        SELECT DISTINCT ON (branch_code)
               branch_code, branch_name, region, branch_status, successor_branch_code,
               effective_date AS info_since
        FROM core.branch_history
        ORDER BY branch_code, effective_date DESC;
    """)
    op.execute("""
        CREATE VIEW core.customer_current AS
        SELECT c.cust_id, c.cust_id_legacy, c.cust_name, c.cust_dob, c.cust_gender,
               h.cust_segment, h.cust_risk_profile, h.effective_date AS info_since
        FROM core.customer c
        LEFT JOIN LATERAL (
            SELECT * FROM core.customer_history h
            WHERE h.cust_id = c.cust_id
            ORDER BY h.effective_date DESC LIMIT 1) h ON true;
    """)
    op.execute("""
        CREATE VIEW core.sales_transaction AS
        WITH typed AS (
            SELECT r.*, NULLIF(upper(trim(r.sales_person_id)), '') AS sp_std
            FROM raw.sales_log r
        )
        SELECT t.txn_id,
               t.txn_date_time,
               t.txn_date_time::date                                         AS txn_date,
               (extract(hour FROM t.txn_date_time) * 60
                + extract(minute FROM t.txn_date_time))::int                 AS time_key,
               upper(trim(t.branch_code))                                    AS branch_code,
               upper(trim(t.product_code))                                   AS product_code,
               core.std_cust_id(t.cust_id)                                   AS cust_id,
               t.channel, t.campaign_code,
               upper(trim(t.currency))                                       AS currency,
               t.amount_local,
               t.sales_person_id                                             AS sales_person_id_typed,
               t.sp_std                                                      AS sales_person_id_std,
               CASE WHEN t.sp_std IS NULL           THEN 'SELF-DIRECTED'
                    WHEN s.sales_person_id IS NOT NULL
                         THEN CASE WHEN t.sp_std = t.sales_person_id THEN 'OK' ELSE 'OK (auto-fixed)' END
                    WHEN c.txn_id IS NULL           THEN 'CONFIRM (not logged)'
                    WHEN c.action IS NOT NULL       THEN 'CONFIRMED (' || lower(c.action) || ')'
                    ELSE 'PENDING CONFIRM' END                               AS sales_person_check,
               CASE WHEN s.sales_person_id IS NOT NULL THEN t.sp_std
                    WHEN c.action IS NOT NULL         THEN c.confirmed_id END AS sales_person_id_corrected,
               t.status
        FROM typed t
        LEFT JOIN core.sales_person s              ON s.sales_person_id = t.sp_std
        LEFT JOIN core.sales_person_confirmation c ON c.txn_id = t.txn_id;
    """)

def downgrade() -> None:
    op.execute("""DROP VIEW core.sales_transaction;""")
    op.execute("""DROP VIEW core.customer_current;""")
    op.execute("""DROP VIEW core.branch_current;""")
    op.execute("""DROP VIEW core.ref_time;""")
    op.execute("""DROP VIEW core.ref_date;""")
