# Bank Retail Sales Data Mart

A rebuild, on mock data, of a retail sales database I helped a bank build: from a messy selling log to a trusted reporting table, first as an **Excel prototype**, then as a **PostgreSQL** database with migrations, a least-privilege loader and automated data-quality checks.

> All data is invented (500 sales, 80 customers, Jan–Jun 2025, Hong Kong branches). Names, IDs, rates and amounts are illustrative. The structure and the problems are the ones I worked with.

## The problem

The bank was formed from a merger of two banks. Its retail selling log (one row per sale: branch, product, customer, currency, amount, salesperson) came from both legacy systems, so the same thing was written in different ways:

| What the log showed | What it breaks |
|---|---|
| Customer IDs in two formats: `'0045128803'` and `45128803` (leading zeros lost) | 96 "customers" in the log for 80 real people |
| Branches renamed and closed mid-year | Reports mix old and new names; closed branches' sales disappear or move |
| Customers change segment and risk profile over time | A sale is judged against today's profile instead of the one at the time |
| Sales in USD, HKD and CNY | Totals can't be added up |
| Salesperson IDs typed by hand (`E11`, `E1100`, ` e105 `) | Commission and performance go to the wrong person, or nobody |

## The design

**Rule:** the raw log is the landing layer and is never edited. Every fix happens downstream, so every number can be traced back to what was captured.

```
raw log  ──►  clean + look up  ──►  3NF reference tables with history  ──►  one big table (OBT)  ──►  checks  ──►  reports
(landing)     (transformation)      (integration layer)                     (data mart)               (DQ)
```

| Layer | Excel prototype | PostgreSQL |
|---|---|---|
| Landing (append-only) | `1_raw_log` | `raw.sales_log` |
| Calendar / time of day | `3_ref_date`, `4_ref_time` | `core.ref_date`, `core.ref_time` |
| Branch: entity + change log | `5_branch`, `6_3nf_branch_history` | `core.branch_current`, `core.branch_history` |
| Product | `7_3nf_product` | `core.product` |
| Customer: fixed facts + change log | `8_3nf_customer`, `9_3nf_customer_history` | `core.customer(_current)`, `core.customer_history` |
| Daily FX (from a Wind / Bloomberg feed) | `10_ref_fx_rate` | `core.fx_rate` |
| Salesperson + confirmation workflow | `11_…`, `12_sales_person_confirmation` | `core.sales_person`, `core.sales_person_confirmation` |
| One big table | `2_enriched_log` | `mart.sales_obt` |
| Data-quality checks | `13_checks` | `dq.checks`, `dq.summary` |
| Reports | `14_report` | `mart.rpt_*` views |

**Key decisions**

- **Natural keys and append-only change logs.** Branch and customer history are stored as one row per change (`effective_date` only); `valid_to` and "current" views are derived. No surrogate keys needed.
- **As-of-date lookups.** Each sale picks up the branch name and status, customer segment and risk profile, and FX rate that were valid on the sale date (`LATERAL` joins in SQL, `MAXIFS` in Excel).
- **Never guess.** Legacy 8-digit customer IDs are rectified by a single rule (`00` + ID); salesperson typos that can be fixed safely are auto-fixed, the rest go to a confirmation table (Acknowledged / Corrected / pending) for a data steward.
- **Checks live in one place, and are tested by breaking them.** Planted errors (unknown product, sale at a closed branch, unlogged typo…) must make the right check FAIL.
- **A one big table on purpose.** One business process at one grain, so a star schema's main benefit (sharing dimensions across fact tables) doesn't apply yet. The OBT is never typed into; every column is looked up or derived, and it is where new, unknown information shows up first. It carries the version keys a fact table would need, if a second process is added later.
- **Derived attributes** (feature engineering): time of day, age at sale, amount in HKD, self-directed vs RM-assisted, a suitability flag (product riskier than the customer's profile at the time).

It meets Inmon's four properties (subject-oriented, integrated, time-variant, non-volatile) for one subject, so it is a **data mart**. In Excel, non-volatility depends on discipline; in PostgreSQL it is enforced by permissions: the loading role can only `INSERT` into the raw layer.

The full reasoning, problem by problem and column by column, is in [docs/design-notes.md](docs/design-notes.md).

## What the SQL version adds

- **Constraints replace half the Excel checks.** Primary keys, foreign keys and `CHECK` constraints reject bad reference data at the door (10-digit customer IDs, `E` + 3 digits salesperson IDs, a closed branch must name its successor, a confirmation is all-or-nothing). The 14 checks in `dq.checks` cover what constraints can't, i.e. the log itself.
- **Version-controlled schema.** Six Alembic migrations (plain SQL), each reversible: `alembic downgrade base` removes everything cleanly.
- **Least privilege.** Reference data is maintained by the admin role; sales are loaded by an `etl` role with `SELECT, INSERT` on `raw` only: `UPDATE`, `DELETE` and `TRUNCATE` are refused.
- **Idempotent loading.** `src/load.py` can be re-run safely; a resolved salesperson confirmation is never overwritten.

Tested end to end: the SQL results match the Excel workbook exactly (HKD 564.6m completed sales, every monthly, segment and branch total, 8 suitability flags), and the checks fail on planted errors.

## Findings (mock data)

- Monthly net sales range HKD 78m–113m with no clear trend; February is the peak (Lunar New Year campaign period).
- Deposits are the largest category and grew from Q1 to Q2.
- All evening and night sales are self-directed; RM-assisted sales happen only in office hours.
- Private customers bring 67% of net sales.
- 8 completed sales (1.7%) were of a product riskier than the customer's profile at the time.

## Repository layout

```
excel/bank_retail_sales_data_mart.xlsx   Excel prototype (15 sheets, live formulas, native charts)
docs/design-notes.md                     design journey and decisions
sql/
  bootstrap/001_setup_db.sql             one-time: database, schemas, etl rights
  migrations/versions/0001…0006          raw → core → mart → dq → reports
  src/load.py                            loads data/*.csv, prints the data-quality summary
  data/                                  mock data exported from the workbook
  queries/examples.sql                   history, closures, to-do list, suitability, age groups
  run_load.bat                           Windows launcher (Task Scheduler)
```

## Run it

Needs PostgreSQL (tested on 16) and Python 3.10+. I run it on my home NAS (PostgreSQL 18 in Docker, alongside my other homelab databases), but any PostgreSQL works.

```bash
cd sql
pip install -r requirements.txt
cp .env.example .env                                   # fill in host, users, passwords

# once, as the admin user (assumes a login role `etl` exists)
psql -h <host> -p 5433 -U <admin> -d postgres -f bootstrap/001_setup_db.sql

alembic upgrade head                                    # create tables and views
python src/load.py                                      # load data, print check summary
```

Expected output ends with: `data-quality checks: ALL PASS (13 pass, 0 fail, 1 info)` (the INFO is 4 salesperson IDs still waiting for confirmation, which is expected work, not an error).
