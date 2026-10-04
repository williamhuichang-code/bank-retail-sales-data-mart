"""report views

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op


revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE VIEW mart.rpt_monthly_sales AS
        SELECT month, round(sum(amount_hkd) / 1e6, 1) AS net_sales_hkd_m
        FROM mart.sales_obt WHERE status = 'Completed' GROUP BY month ORDER BY month;
    """)
    op.execute("""
        CREATE VIEW mart.rpt_category_quarter AS
        SELECT product_category,
               round(sum(amount_hkd) FILTER (WHERE quarter = 'Q1') / 1e6, 1) AS q1_hkd_m,
               round(sum(amount_hkd) FILTER (WHERE quarter = 'Q2') / 1e6, 1) AS q2_hkd_m
        FROM mart.sales_obt WHERE status = 'Completed' GROUP BY product_category ORDER BY product_category;
    """)
    op.execute("""
        CREATE VIEW mart.rpt_time_of_day AS
        SELECT day_part,
               count(*) FILTER (WHERE sales_person_check <> 'SELF-DIRECTED') AS rm_assisted,
               count(*) FILTER (WHERE sales_person_check =  'SELF-DIRECTED') AS self_directed
        FROM mart.sales_obt WHERE status = 'Completed' GROUP BY day_part
        ORDER BY array_position(ARRAY['Morning','Afternoon','Evening','Night'], day_part);
    """)
    op.execute("""
        CREATE VIEW mart.rpt_segment AS
        SELECT cust_segment, round(sum(amount_hkd) / 1e6, 1) AS net_sales_hkd_m
        FROM mart.sales_obt WHERE status = 'Completed' GROUP BY cust_segment
        ORDER BY array_position(ARRAY['Mass','Affluent','Private'], cust_segment);
    """)
    op.execute("""
        CREATE VIEW mart.rpt_branch AS
        SELECT o.branch_code,
               bc.branch_name || CASE WHEN bc.branch_status = 'Closed' THEN ' (closed)' ELSE '' END AS branch_now,
               round(sum(o.amount_hkd) / 1e6, 1) AS net_sales_hkd_m
        FROM mart.sales_obt o JOIN core.branch_current bc USING (branch_code)
        WHERE o.status = 'Completed'
        GROUP BY o.branch_code, branch_now ORDER BY o.branch_code;
    """)
    op.execute("""
        CREATE VIEW mart.rpt_suitability AS
        SELECT count(*) FILTER (WHERE product_risk_level > cust_risk_profile)            AS sales_flagged,
               round(100.0 * count(*) FILTER (WHERE product_risk_level > cust_risk_profile)
                     / count(*), 1)                                                     AS pct_of_completed
        FROM mart.sales_obt WHERE status = 'Completed';
    """)


def downgrade() -> None:
    op.execute("""DROP VIEW mart.rpt_suitability;""")
    op.execute("""DROP VIEW mart.rpt_branch;""")
    op.execute("""DROP VIEW mart.rpt_segment;""")
    op.execute("""DROP VIEW mart.rpt_time_of_day;""")
    op.execute("""DROP VIEW mart.rpt_category_quarter;""")
    op.execute("""DROP VIEW mart.rpt_monthly_sales;""")
