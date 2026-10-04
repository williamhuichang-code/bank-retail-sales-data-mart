"""raw sales log

Revision ID: 0001
Revises: 
Create Date: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op


revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE raw.sales_log (
            txn_id          text PRIMARY KEY,
            txn_date_time   timestamp NOT NULL,   -- local (Hong Kong) time, as captured
            branch_code     text,
            product_code    text,
            cust_id         text,                 -- as received: legacy IDs may have lost '00'
            channel         text,
            campaign_code   text,
            currency        text,
            amount_local    numeric(18,2),
            sales_person_id text,                 -- as typed by the salesperson
            status          text,
            loaded_at       timestamptz NOT NULL DEFAULT now()
        );
    """)

def downgrade() -> None:
    op.execute("""DROP TABLE raw.sales_log;""")
