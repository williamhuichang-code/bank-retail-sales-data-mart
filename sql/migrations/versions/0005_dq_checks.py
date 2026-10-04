"""data-quality checks

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op


revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE VIEW dq.checks AS
        WITH c(area, check_name, violations) AS (
        SELECT 'Raw log', 'txn_id format is T + 5 digits', (SELECT count(*) FROM raw.sales_log WHERE txn_id !~ '^T[0-9]{5}$')::int
        UNION ALL
        SELECT 'OBT', 'every raw row appears exactly once in the OBT', (SELECT abs((SELECT count(*) FROM mart.sales_obt) - (SELECT count(*) FROM raw.sales_log)))::int
        UNION ALL
        SELECT 'Date / time', 'every sale date exists in core.ref_date', (SELECT count(*) FROM mart.sales_obt WHERE year IS NULL)::int
        UNION ALL
        SELECT 'Date / time', 'every sale time exists in core.ref_time', (SELECT count(*) FROM mart.sales_obt WHERE day_part IS NULL)::int
        UNION ALL
        SELECT 'Branch', 'every sale finds its branch version on the sale date', (SELECT count(*) FROM mart.sales_obt WHERE branch_info_since IS NULL)::int
        UNION ALL
        SELECT 'Branch', 'no sale is booked to a branch closed on the sale date', (SELECT count(*) FROM mart.sales_obt WHERE branch_status = 'Closed')::int
        UNION ALL
        SELECT 'Product', 'every sale finds its product', (SELECT count(*) FROM mart.sales_obt WHERE product_name IS NULL)::int
        UNION ALL
        SELECT 'Customer', 'every cust_id in the log rectifies to 10 digits', (SELECT count(*) FROM core.sales_transaction WHERE cust_id IS NULL)::int
        UNION ALL
        SELECT 'Customer', 'every sale finds its customer', (SELECT count(*) FROM mart.sales_obt WHERE cust_name IS NULL)::int
        UNION ALL
        SELECT 'Customer', 'every sale finds its segment / risk version', (SELECT count(*) FROM mart.sales_obt WHERE cust_info_since IS NULL)::int
        UNION ALL
        SELECT 'Customer', 'customers are 18+ at onboarding', (SELECT count(*) FROM (SELECT cust_id, min(effective_date) AS onboarded FROM core.customer_history GROUP BY cust_id) o
                 JOIN core.customer c USING (cust_id) WHERE age(o.onboarded, c.cust_dob) < interval '18 years')::int
        UNION ALL
        SELECT 'FX', 'every sale finds a rate on or before its date', (SELECT count(*) FROM mart.sales_obt WHERE amount_hkd IS NULL)::int
        UNION ALL
        SELECT 'Salesperson', 'every mistyped ID is logged for confirmation', (SELECT count(*) FROM core.sales_transaction WHERE sales_person_check = 'CONFIRM (not logged)')::int
        UNION ALL
        SELECT 'Salesperson', 'sales still waiting for confirmation (expected work)', (SELECT count(*) FROM core.sales_transaction WHERE sales_person_check = 'PENDING CONFIRM')::int
        )
        SELECT area, check_name, violations,
               CASE WHEN violations = 0 THEN 'PASS'
                    WHEN check_name LIKE '%expected work%' THEN 'INFO'
                    ELSE 'FAIL' END AS result
        FROM c;
    """)
    op.execute("""
        CREATE VIEW dq.summary AS
        SELECT CASE WHEN count(*) FILTER (WHERE result = 'FAIL') = 0 THEN 'ALL PASS' ELSE 'FAIL' END AS overall,
               count(*) FILTER (WHERE result = 'PASS') AS passed,
               count(*) FILTER (WHERE result = 'FAIL') AS failed,
               count(*) FILTER (WHERE result = 'INFO') AS info
        FROM dq.checks;
    """)


def downgrade() -> None:
    op.execute("""DROP VIEW dq.summary;""")
    op.execute("""DROP VIEW dq.checks;""")
