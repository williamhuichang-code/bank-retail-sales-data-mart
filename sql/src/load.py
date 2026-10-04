"""Load the mock bank sales data (CSV) into Postgres.

Two kinds of data, two roles:
- Reference data (branches, products, customers, FX rates, salespeople, confirmations)
  is maintained by the data steward -> loaded with the admin (migrate) role.
- Sales are new facts arriving from the selling system -> loaded into raw.sales_log
  with the least-privilege `etl` role, which can only INSERT (append-only).

Idempotent: every insert uses ON CONFLICT, so re-running never duplicates rows.
Order matters because of foreign keys: reference -> raw sales -> confirmations.
"""
import csv
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

DATA = Path(__file__).resolve().parent.parent / "data"


def rows(name):
    """CSV rows as dicts, with empty strings turned into NULLs."""
    with open(DATA / name, newline="", encoding="utf-8") as f:
        return [{k: (v if v != "" else None) for k, v in r.items()} for r in csv.DictReader(f)]


def connect(user_var, password_var):
    return psycopg.connect(
        host=os.environ["DB_HOST"],
        port=os.environ["DB_PORT"],
        dbname=os.environ["DB_NAME"],
        user=os.environ[user_var],
        password=os.environ[password_var],
    )


REFERENCE = [
    # (csv file, insert statement)
    ("branch_history.csv", """
        INSERT INTO core.branch (branch_code) VALUES (%(branch_code)s)
        ON CONFLICT DO NOTHING"""),
    ("branch_history.csv", """
        INSERT INTO core.branch_history
            (branch_code, effective_date, branch_name, region, branch_status, successor_branch_code)
        VALUES (%(branch_code)s, %(effective_date)s, %(branch_name)s, %(region)s,
                %(branch_status)s, %(successor_branch_code)s)
        ON CONFLICT DO NOTHING"""),
    ("product.csv", """
        INSERT INTO core.product (product_code, product_name, product_category, product_risk_level, fee_rate)
        VALUES (%(product_code)s, %(product_name)s, %(product_category)s, %(product_risk_level)s, %(fee_rate)s)
        ON CONFLICT DO NOTHING"""),
    ("customer.csv", """
        INSERT INTO core.customer (cust_id, cust_id_legacy, cust_name, cust_dob, cust_gender)
        VALUES (core.std_cust_id(%(cust_id_legacy)s), %(cust_id_legacy)s, %(cust_name)s,
                %(cust_dob)s, %(cust_gender)s)
        ON CONFLICT DO NOTHING"""),
    ("customer_history.csv", """
        INSERT INTO core.customer_history (cust_id, effective_date, cust_segment, cust_risk_profile, change_reason)
        VALUES (%(cust_id)s, %(effective_date)s, %(cust_segment)s, %(cust_risk_profile)s, %(change_reason)s)
        ON CONFLICT DO NOTHING"""),
    ("fx_rate.csv", """
        INSERT INTO core.fx_rate (currency_code, rate_date, units_per_usd)
        VALUES (%(currency_code)s, %(rate_date)s, %(units_per_usd)s)
        ON CONFLICT DO NOTHING"""),
    ("sales_person.csv", """
        INSERT INTO core.sales_person (sales_person_id, sales_person_name)
        VALUES (%(sales_person_id)s, %(sales_person_name)s)
        ON CONFLICT DO NOTHING"""),
]

RAW_SALES = """
    INSERT INTO raw.sales_log
        (txn_id, txn_date_time, branch_code, product_code, cust_id, channel, campaign_code,
         currency, amount_local, sales_person_id, status)
    VALUES (%(txn_id)s, %(txn_date_time)s, %(branch_code)s, %(product_code)s, %(cust_id)s,
            %(channel)s, %(campaign_code)s, %(currency)s, %(amount_local)s,
            %(sales_person_id)s, %(status)s)
    ON CONFLICT (txn_id) DO NOTHING"""

# A pending confirmation may later be resolved; a resolved one is never overwritten.
CONFIRMATIONS = """
    INSERT INTO core.sales_person_confirmation (txn_id, action, confirmed_id, confirmed_by, confirmed_date)
    VALUES (%(txn_id)s, %(action)s, %(confirmed_id)s, %(confirmed_by)s, %(confirmed_date)s)
    ON CONFLICT (txn_id) DO UPDATE
    SET action = EXCLUDED.action, confirmed_id = EXCLUDED.confirmed_id,
        confirmed_by = EXCLUDED.confirmed_by, confirmed_date = EXCLUDED.confirmed_date
    WHERE core.sales_person_confirmation.action IS NULL"""


def main():
    load_dotenv()  # reads sql/.env

    with connect("MIGRATE_DB_USER", "MIGRATE_DB_PASSWORD") as conn, conn.cursor() as cur:
        for name, sql in REFERENCE:
            data = rows(name)
            cur.executemany(sql, data)
            print(f"reference  {name:<28} {len(data):>4} rows read")
        conn.commit()

    with connect("ETL_DB_USER", "ETL_DB_PASSWORD") as conn, conn.cursor() as cur:
        data = rows("sales_log.csv")
        cur.executemany(RAW_SALES, data)
        conn.commit()
        print(f"raw        {'sales_log.csv':<28} {len(data):>4} rows read (as etl)")

    with connect("MIGRATE_DB_USER", "MIGRATE_DB_PASSWORD") as conn, conn.cursor() as cur:
        data = rows("sales_person_confirmation.csv")
        cur.executemany(CONFIRMATIONS, data)
        conn.commit()
        print(f"reference  {'sales_person_confirmation.csv':<28} {len(data):>4} rows read")

        cur.execute("SELECT overall, passed, failed, info FROM dq.summary")
        overall, passed, failed, info = cur.fetchone()
        print(f"\ndata-quality checks: {overall} ({passed} pass, {failed} fail, {info} info)")
        if overall != "ALL PASS":
            cur.execute("SELECT area, check_name, violations FROM dq.checks WHERE result = 'FAIL'")
            for area, name, n in cur.fetchall():
                print(f"  FAIL  {area}: {name} ({n})")


if __name__ == "__main__":
    main()
