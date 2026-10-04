# Bank Retail Sales Database: Design Notes

How each design decision traces back to a problem in the raw selling log.

**Approach.** Start from the raw log (one row per sale), which sets the grain of the future fact table. Look forward: how will the data be reported, and what will go wrong? Look backward: which information needs a single, automated entry point so the problem can't happen at the source?

**Rule.** `raw_log` is the landing layer and is never edited. Every fix happens downstream, so any number can be traced back to what was originally captured.


## Final design (current state)

*The sections after this one are the design journey, in the order decisions were made; some intermediate steps (e.g. `3nf_branch`, `ref_branch_daily`) were later replaced. This summary describes the workbook as it is now.*

| Sheet | Role | Key |
|---|---|---|
| `1_raw_log` | Landing layer: 500 sales as captured, never edited. Facts + foreign keys only (11 columns) | `txn_id` |
| `2_enriched_log` | Live copy of the raw log + looked-up columns (date/time, branch as of sale, product, customer as of sale, FX → HKD, salesperson). Cleaned keys end in `_std` | `txn_id` |
| `3_ref_date`, `4_ref_time` | Date and time-of-day references; calendar starts at the earliest sale | `date`, `time_key` |
| `5_branch` | Branch entity, today's view (name, region, status, successor), calculated from the history | `branch_code` |
| `6_3nf_branch_history` | Append-only change log: name, region, status, successor (renames, closures) | `branch_code + effective_date` |
| `7_3nf_product` | Static product attributes | `product_code` |
| `8_3nf_customer` | Fixed customer facts; legacy ID vs rectified ID; today's segment/risk | rectified `cust_id` |
| `9_3nf_customer_history` | Append-only change log: segment, risk profile (from AUM, authorised; sales customers only) | `cust_id + effective_date` |
| `10_ref_fx_rate` | Daily FX rates (Wind / Bloomberg API), units per USD | `currency_code + rate_date` |
| `11_3nf_sales_person` | Salesperson ID → name | `sales_person_id` |
| `12_sales_person_confirmation` | Workflow for mistyped IDs: Acknowledged / Corrected / pending | `txn_id` |
| `13_checks` | All data-quality checks (28): PASS / FAIL / INFO | – |

**Recurring patterns:** facts vs reference data · append-only change logs with derived `valid_to` · as-of-date lookups (branch, customer, FX) · current view vs history · never guess (CHECK / PENDING) · all checks in one place, tested by breaking them.

**Deliberately not modelled yet:** reference tables for `channel`, `campaign_code`, `status` (system-generated, not typed by hand); salesperson employment history.

---

## Where raw_log sits in the architecture

```
Source systems  →  Staging / landing  →  Integration layer   →  Data marts      →  Reports
                   (raw_log)             (3NF tables)            (star schema)
                   bronze                silver                  gold
```

| This project | Industry role |
|---|---|
| `raw_log` | Staging / landing layer (bronze): data as captured, never edited |
| Cleaning and checks | Transformation (ETL/ELT): turns raw data into trusted data |
| 3NF tables | Integration layer (silver): each fact stored once, with keys and history |
| Star schema | Data mart (gold): the sales mart, shaped for reporting |
| Reports | Consumption layer |

- **Inmon** builds a normalised (3NF) enterprise warehouse first, then data marts from it. This project follows that order.
- **Kimball** goes from staging straight to star-schema marts, linked by shared (conformed) dimensions.
- A real bank's source system is usually normalised already. A flat log like this comes from an **extract** (tables joined for convenience) or a **manually kept spreadsheet** (free-text entry). `raw_log` has both kinds of fields, so the 3NF layer had to be rebuilt from it.

### Background: a log from merged legacy systems

The bank was formed from a merger of two banks, and the selling log comes from legacy systems where both banks' information is mixed together. This is a common root cause of messy data (post-merger data integration):

- **Different conventions for the same thing:** codes, ID formats and naming differ between the two banks.
- **Overlapping keys:** the same real-world customer, branch or product can appear under different codes.
- **Partial migrations:** one row can mix fields captured under the old and new conventions.

| Merger problem | Data engineering answer | Where it lives in this project |
|---|---|---|
| Two codes for one thing | Crosswalk (mapping) tables to one standard code | Between `raw_log` and 3NF |
| Same entity in both banks | Master data management: one "golden record" per entity | 3NF entity tables |
| Need to know where a value came from | Lineage: keep a source-system marker | `raw_log` → 3NF |
| Reports must treat both banks as one | Conformed dimensions shared across all reports | Star schema |

### My thinking journey: which schema shape?

1. **One core.** `raw_log` records one business process (sales) at one grain (one row per sale), so there is **one fact table**: `fact_sales`.
2. **So a star or a snowflake, not a galaxy.**
   - **Star:** one fact table surrounded by flat dimensions (date, customer, product, branch, salesperson, channel, campaign).
   - **Snowflake:** the same, but some dimensions are split into sub-tables (branch → region, product → category).
   - **Galaxy (fact constellation):** several fact tables sharing dimensions. That would only be needed if another process at a different grain were added later, such as monthly RM payouts, sales targets or customer holdings.
3. **My design order: raw_log → dimensions → 3NF.**
   - Start from the fact (the grain) and ask "by what will people report?" Each answer becomes a dimension: date, customer, product, branch, salesperson, channel, campaign. This is close to Kimball's approach (staging straight to a star).
   - Then normalise each dimension further: split out anything that doesn't depend only on that dimension's key. For example, `dim_branch` holds region, but the region name depends on the region, so region becomes its own table. Taken all the way, this snowflaking ends in 3NF.
   - **Watch 1: some dependencies hide in the fact.** The FX rate depends on currency + month, and the fee income rate depends on product + date. Neither belongs to one dimension, so the fact table needs normalising too.
   - **Watch 2: history must be separated.** A customer's name and date of birth are fixed, but their segment changes over time, so normalising `dim_customer` gives a customer table plus a segment-history table.
   - **Design order vs data flow order.** I design dimension-first, but in the finished system data still flows raw → cleaned → 3NF → star. The 3NF layer is the trusted single entry point the star is loaded from, and the star deliberately **denormalises** the dimensions again so reports need fewer joins.
4. **Why dimension-first fits my case: I'm using the data, not designing a new system.**
   - **My case is data-driven (bottom-up).** I start from the data that already exists, collect what downstream reports need, and reverse-engineer the structure from it. This is typical for analysts and BI teams working with data from systems they didn't build.
   - **Starting from 3NF is requirements-driven (top-down).** That's the route for building a new database for a company: business rules → conceptual model (entities and relationships) → logical model (tables, keys, 3NF) → physical model (the actual database, types and indexes).
   - **I still pass through the same levels, in reverse.** Grouping columns into dimensions is finding the entities (conceptual); splitting them by dependencies is the logical model; building the tables is the physical model.
5. **Choice: star.** It is simpler to query and to explain. The full hierarchy (branch → region, product → category) is still kept in the 3NF layer, so nothing is lost.

---

## Problems and solutions

### Problem 0: dependencies are not enforced (overall)

- **What we see:** one wide row per sale. Every row repeats descriptive information about the branch, salesperson, customer and product, alongside the facts of the sale itself. Nothing stops the same branch, customer or product from being written differently on different rows, and many small flaws (typos, lost leading zeros, renamed branches) are already in the data.
- **Why it matters:** reports group and filter by these repeated attributes. If one thing is written two ways, totals split or double count, and nobody can tell which version is right.
- **Solution:** keep `raw_log` as the untouched landing layer. Downstream, give each kind of thing (branch, salesperson, customer, product…) one table with its own key, so each attribute is stored once and depends only on that key (3NF). The sale keeps only its own facts plus keys. The specific flaws below are each solved by part of this design.

### Problem 1: customer IDs in mixed formats (legacy leading zeros)

- **What we see:** `cust_id` should be a 10-digit code, but IDs starting with `00` arrive in two forms. Some keep their zeros as text (`'0045128803'`); others have lost them and are stored as numbers (`45128803`). This comes from the legacy systems, which used different formats. In the 500 rows:
  - 59 rows have an ID that lost its leading zeros;
  - 16 of the 20 customers whose ID starts with 0 appear **both ways**;
  - so the log holds **96 distinct `cust_id` values for only 80 real customers**.
  - Example: Li Na is `45128803` in T00022 but `'0045128803'` in T00218.
- **Why it matters:** any count or grouping by customer splits one person into two. Customer numbers are inflated (96 instead of 80), per-customer sales are understated, and joins to customer information miss rows.
- **Solution:**
  - **Rule:** a customer ID is an identifier, not a number, so it's always stored as **10-character text**.
  - **Transformation:** standardise every incoming ID: trim spaces, then pad with leading zeros to 10 characters (Excel: `RIGHT(REPT("0",10)&TRIM(id),10)`; SQL: `LPAD(TRIM(id),10,'0')`).
  - **Quality check:** flag any ID that isn't exactly 10 digits after cleaning, instead of guessing.
  - **3NF:** the customer table's primary key is the cleaned text ID, so each customer exists once.
  - **Long term:** fix it at the source, so new records are captured as 10-character text.
- **Layer:** `raw_log` keeps the ID as received; cleaning happens in the transformation step; the 3NF customer table holds the standard form.

Each problem is recorded as:

- **What we see:** evidence in `raw_log` (with example rows)
- **Why it matters:** what breaks in reporting
- **Solution:** the data engineering fix, and which layer it lives in

<!-- Problems are added one by one as we go through them. -->

---

## Column-by-column review

Each `raw_log` column is assigned to the fact or a dimension, with the checks or fixes it needs.

**Mindset: don't trust an unknown source. Every column gets the same checklist**, based on the standard data quality dimensions (e.g. DAMA). Only the answers differ by column, so each column below lists just what is special about it.

| Dimension | Question for each column | Example in this log |
|---|---|---|
| **Completeness** | Is it filled when it should be? | Blank `sales_person` is allowed (self-directed); blank `cust_id` is not |
| **Uniqueness** | Should values be unique? | `txn_id` yes; `cust_id` no (repeat customers) |
| **Validity: type and format** | Right type, length and pattern? | `cust_id` is 10-digit text; dates are real dates |
| **Validity: range and domain** | Within the allowed values? | `status` only Completed / Cancelled / Pending; amount > 0 |
| **Consistency** | Does it agree with other columns and rows? | One `branch_code` has one name on a given date |
| **Referential integrity** | Does it exist in the reference list? | `product_code` exists in the product table |

In the SQL version, these become automated tests on every load, with failing rows sent to a quarantine table (see `txn_id`).

### `txn_id`: fact (degenerate dimension)

- **Status:** clean. It comes straight from the source system. In the 500 rows: no blanks, no duplicates, all in the format `T` + 5 digits.
- **Principle:** be conservative with an unknown source and check, not trust, even a column that looks clean. Everything else depends on this key.
- **Checks:**
  1. **Unique (and not blank):** it is the primary key of a sale. A duplicate usually means the same extract was loaded twice.
  2. **Same length** on every row.
  3. **Consistent structure:** same case (all upper or all lower), same number of letters and digits in the same positions. This is called **pattern profiling**: replace every letter with `A` and every digit with `9`, then count the patterns. `T00123` → `A99999`. One pattern means consistent; any other (`t0123`, `TX00123`) stands out at once.
  4. **Same sale under two IDs:** compare content (customer, date-time, product, amount). This is a real risk after a migration, where both legacy systems may have recorded the same sale.
  - Result on the 500 rows: all pass.
- **Excel version:** no action needed.
- **SQL version (later, done properly):**
  - **Profile first:** a query that groups by `LENGTH(txn_id)` and by the A/9 pattern, to see what really arrives before writing rules.
  - **Validate in staging:** rows that fail go to a **quarantine (reject) table** with the reason, instead of stopping the whole load or slipping through.
  - **Enforce in the target table:** `PRIMARY KEY` (unique + not null) and a `CHECK` constraint on the format (e.g. PostgreSQL `CHECK (txn_id ~ '^T[0-9]{5}$')`), so bad IDs can't get in even by mistake.
  - **Automate as data tests** that run on every load (e.g. dbt's `unique` and `not_null` tests).
- **Role:** stays in the fact table as a **degenerate dimension**: an identifier with no attributes of its own, so no dimension table is needed. It lets any reported number be traced back to the original sale.

### `txn_date_time`: fact → `dim_date` + `dim_time`

- **Idea:** many attributes can be derived from the timestamp (year, quarter, month, week, day of week, time of day), and these may show patterns in customer behaviour. Derive them **once** in a date dimension, so every report slices time the same way instead of recalculating it.
- **Design: split into two dimensions (standard Kimball practice).**
  - **`dim_date`:** one row per calendar day (181 rows for Jan–Jun 2025): year, quarter, month, week, day of week, weekend flag, month-end flag. Business calendars belong here too: **public holidays** and **campaign periods** (e.g. CNY), which often explain behaviour better than the month.
  - **`dim_time`:** one row per hour or minute of the day, with buckets (morning / lunch / afternoon / evening / after hours).
  - **Why split:** a combined date-time dimension would need a row for every minute of every day (~260,000 rows for six months); two small dimensions cover the same with a few hundred rows.
  - The fact keeps `date_key` (yyyymmdd) and `time_key`; the original timestamp can stay for tracing.
- **Behaviour already visible in the data:**
  - RM-assisted sales (391): weekdays only, 09:00–17:59.
  - Self-directed sales (109): 07:00–22:59, with 33 at weekends and 31 after 18:00.
  - So digital channels capture demand outside office hours: a ready-made insight for the report.
- **Column-specific checks** (on top of the standard checklist):
  - A real date-time, inside the extract period (2025-01-02 to 2025-06-30), not in the future.
  - **Consistency with branch:** the branch was open on that date (catches sales booked to closed branches).
  - **Consistency with channel:** an RM-assisted branch sale late at night or at the weekend is suspicious.
  - **Time zone:** both legacy systems must record local (Hong Kong) time.

### `branch_code`: fact → `dim_branch`

- **Status:** generally clean (B01–B05), and it is the stable key: the branch name can change, the code doesn't.
- **Risk: a new code arrives** (e.g. `B101`) that the 3NF branch table doesn't know yet.
- **Solution: inferred member (late-arriving dimension) pattern**, built into the SQL version:
  1. **Detect:** on every load, check each `branch_code` exists in the 3NF branch table (referential integrity).
  2. **Keep the sale, flag the code:** create a placeholder branch row, e.g. `Other: B101 (pending review)`, with `is_inferred = Y`. The sale still loads and counts in totals, and the flag is visible in reports, so nothing is lost and nothing is silent.
  3. **Alert a person:** an exception report lists new codes for the domain expert (in industry: the **data steward**, the business owner of reference data).
  4. **Resolve:** once confirmed (name, region, opening date), update the placeholder row in place. Sales already loaded show the right branch automatically, with no reload.
- **Why not one "Unknown" bucket:** simpler, but it loses which code arrived. Keeping the code makes follow-up easy.
- The same pattern applies to any code column: product, channel, campaign, salesperson ID.

### `branch_name`: dimension attribute that changes over time

- **Key insight:** the branch name depends on the branch code **and the date**, not on the code alone. A branch can be renamed (B02: "Tsim Sha Tsui" until 31 Mar 2025, "TST Harbour City" from 1 Apr 2025).
- **Why it matters for reports:** grouping by name splits one branch in two. B02's completed sales of US$26.1M show as "Tsim Sha Tsui" US$13.8M (93 sales) and "TST Harbour City" US$12.2M (92 sales), so it looks like two weaker branches.
- **Region can change too:** a branch can move to another (management) region in a reorganisation without moving physically. So region also depends on code + date.
- **Database integrity (3NF): one branch history table.**
  - `branch_history(branch_code, valid_from, valid_to, branch_name, region_id, status)`, key = `branch_code + valid_from`. A new row whenever **any** of these changes (rename, region move, closure).
  - The branch table keeps only facts that never change (code, opening date).
  - Any change = close the old row, open a new one: entered once, in one place.
  - **Alternative considered:** one history table per attribute (`branch_name_history`, `branch_region_history`, …). Stricter, since each table changes only when its own attribute does, but every report needs one as-of join per attribute. **Chosen: one table**, because one as-of join returns the whole branch as it was on any date, it maps directly to a Type 2 `dim_branch` (one version = one row), and it matches the employee assignment design.
- **Reporting (star schema): a Slowly Changing Dimension (SCD) decision.**

| Option | What reports show | When it's right |
|---|---|---|
| Type 1: overwrite | Today's name for all history | Branch performance over time (one line per branch) |
| Type 2: new row per version | The name at the time of each sale | Audit; "what did the March report say?" |
| Hybrid: Type 2 + a current-name column | Both; the report chooses | Usually best, and cheap to add |

- **Rules:**
  - Reports **group by `branch_code` (or branch key), never by name**. The name is only a label.
  - The same SCD choice applies to region: sales under the region **at the time of sale** (as it was) or under **today's** regions (restated). After a reorganisation, management usually wants the restated view to compare years under one structure, so `dim_branch` carries both (hybrid).
  - **Consistency check:** compare the raw log's `branch_name` with the reference name valid on the sale date. Flag mismatches; never trust the raw name.

### Decision: the log keeps only `branch_code`; name and region move to `3nf_branch`

- Head office systems typically know branches only by code, so `branch_name` and `region` don't belong on each sale. They were removed from `1_raw_log`.
- New static reference table `3nf_branch(branch_code PK, branch_name, region)`, one row per branch, maintained in one place.
- Check (live formula): every `branch_code` in the log exists in `3nf_branch` (500 of 500, PASS).
- Consequence: the B02 rename is no longer visible in the sales data, so it must live in the branch reference data. For now the table holds current names only; history and closures are the next step.

### Update: branch lookups are as-of-date (`3nf_branch_history`)

- **The real question:** on a given **date**, what was branch_code X called, and which region was it in? So the logical lookup key is **branch_code + date** (no time needed: names don't change mid-day).
- **Two ways to store it:**
  - A. One row per day per branch: exact match on `(date, branch_code)`. Literal, but 905 rows for six months and growing daily.
  - B. One row per version: `(branch_code, valid_from)` plus `valid_to`; find the row where the code matches and the date falls in the range. **Chosen**: 6 rows, grows only when something changes.
- `3nf_branch` became `3nf_branch_history` (B02 has two versions). Checks: no overlapping versions; every one of the 500 sales finds exactly one version (PASS).
- `2_enriched_log` now has `txn_date` (date part of `txn_date_time`) before the branch group, and `branch_name` / `region` are looked up by `branch_code_clean` + `txn_date`. B02 shows "Tsim Sha Tsui" up to 31 Mar and "TST Harbour City" from 1 Apr.

### Decision: versions + a generated daily table (`ref_branch_daily`)

- `2_enriched_log` carries a composite key `branch_date_key` = branch_code + `_` + yyyymmdd (e.g. `B01_20250102`): literally "which branch, on which day".
- **Design chosen: two tables, one source of truth.**
  - `3nf_branch_history`: the version table people maintain (one row per change, valid_from / valid_to). All edits happen here.
  - `ref_branch_daily`: **generated, never edited**. One row per branch per day (785 rows), keyed by `branch_date_key`, with name and region looked up from the version table for that day.
  - The log then uses a plain **exact match** on `branch_date_key`: simple to read and to check.
- **Why:** edits stay in one place (a rename = one new version row), while lookups stay simple. A daily table alone would need hundreds of edits per rename; a version table alone needs range lookups everywhere.
- **Checks:** no duplicate keys, no day without a version, every sale finds its branch-day (all PASS).
- **SQL version:** the daily table becomes a query, not a stored table: a calendar (date spine) joined to the version table on `date BETWEEN valid_from AND valid_to`.

### Refinement: the branch history is an append-only change log

- `3nf_branch_history` stores only **facts**: `branch_code`, `effective_date`, `branch_name`, `region`. A row is added when a branch_code is first set up, and a new row only when its name or region changes. Existing rows are never edited.
- **`valid_to` is no longer stored.** It is derived data (the day before the next change), and storing it allows inconsistencies: gaps or overlaps when one row is edited and its neighbour isn't. Derived `valid_to` / `is_current` are shown as formula columns for readability only.
- **Version on a date** = the latest row for that branch with `effective_date <= date`. `ref_branch_daily` does this lookup, so the log keeps its exact match on `branch_date_key`.
- The overlap check is gone (the design can't overlap); a duplicate check on `branch_code + effective_date` remains.

### Simplification: no daily table; the log looks up the change log directly

- `ref_branch_daily` was removed. `3nf_branch_history` alone is the reference.
- **As-of lookup rule:** for each sale, take the branch's latest `effective_date` **on or before the sale date**, and use that row's name and region.
- `2_enriched_log` stores that date as `branch_effective_date`. Together with `branch_code` it is a **foreign key** to the history table's primary key (`branch_code + effective_date`), so name and region become an exact match on it.
- Result: every sale points to exactly one branch version (B02 → "Tsim Sha Tsui" up to 31 Mar, "TST Harbour City" from 1 Apr).

### Date and time attributes come from reference tables (`ref_date`, `ref_time`)

- The enriched log only extracts the **keys** from the timestamp: `txn_date` (the day) and `txn_time` (rounded to the minute). Every attribute is then **looked up**, never recalculated in the log.
- `ref_date`: one row per calendar day (2025): year, quarter, month, ISO week, weekday. Calculated once, in one place, so every table defines them the same way. Holidays and campaign periods can be added as columns later.
- `ref_time`: one row per minute (time_key 0–1439): time, hour, day_part (Morning 06–11, Afternoon 12–17, Evening 18–21, Night 22–05, an assumption changed in one place).
- Kept as two tables, not one per minute of every day: 365 + 1,440 rows (this is the standard date/time dimension split).
- Check: every sale finds its date and time (0 NOT FOUND); looked-up values match an independent calculation.
- First insight from day_part: all 31 evening/night sales are self-directed (app or phone); RM-assisted sales are only morning and afternoon.

### `sales_person_id`: the log holds only the ID a salesperson types

- **How the data is captured:** a salesperson records a sale by typing their ID. The name is not in the log; it is reference data in `11_3nf_sales_person` (ID → name) and is enriched by lookup, like the branch name.
- **The ID is the key, never the name:** two different people are both called "Michael Chan" (E108, E109), so the name can't identify a person.
- **Position:** `sales_person_id` sits after `fx_to_usd`, before `status`, in `1_raw_log`.
- **Typing mistakes (22 of 391 RM sales):**
  - 8 differ only in case or spaces (`e104`, ` E110`): fixed automatically by `UPPER(TRIM())`, flagged **OK (auto-fixed)** (yellow) so the fix stays visible.
  - 14 are not valid IDs at all: letter O for zero (`E1O3`), swapped digits (`E140`), missing digit (`E14`), extra digit (`E1100`). Flagged **CONFIRM** (red): a person must decide. `E11` is a good example of why we don't guess: it could be E101 or E111.
  - Blank = **SELF-DIRECTED** (no salesperson).
- **Enriched group:** `sales_person_id` (cleaned) → `sales_person_check` (OK / OK (auto-fixed) / SELF-DIRECTED / CONFIRM) → `sales_person_name`.
- **Reconciliation check:** matched (377) + self-directed (109) + to confirm (14) = 500 sales: PASS.
- **Limitation to state honestly:** a wrong but *valid* ID (e.g. E104 typed as E101) can't be caught by format or existence checks. It would need a business rule (e.g. that person wasn't working that day), which comes with salesperson history.
- **Next:** the confirmation workflow (where a person's decision is recorded), and each salesperson's branch and role over time.

### Branch entity vs branch history; product table

- **`5_branch` (the branch entity):** one row per `branch_code` with its **current** name and region, the actual, newest state of each branch. Only the code is typed; name, region and `info_since` are calculated from the latest change in `6_3nf_branch_history`, so nothing is entered twice.
  - Checks: every code in the log exists here, and every code in the history table is listed here (no orphan history rows).
- **`6_3nf_branch_history`** (renamed from `4_3nf_branch_history`): the append-only change log. The log's as-of lookups (name at the time of sale) still use this table.
- **Two views of one branch:** `5_branch` answers "what is it called today?"; the history answers "what was it called on the sale date?". This is the Type 1 vs Type 2 choice from earlier, now as two tables.
- **`7_3nf_product`:** `product_code` (PK), name, category, risk level, fee rate. The log keeps only `product_code` (a foreign key). In the 500 sales each code always had identical attributes, so a static table is enough. Category and risk level could become small lookup tables later (stricter 3NF / snowflake).
- **Sheet order:** 1 raw log, 2 enriched log, 3 date, 4 time, 5 branch, 6 branch history, 7 product, 8 salesperson (renumbered from 5).

### Customer: fixed facts vs changing attributes (`8_3nf_customer`, `9_3nf_customer_history`)

- **Finding:** name, date of birth and gender never vary for a customer, but **segment** changed for 8 customers and **risk profile** for 11 during the half-year (e.g. Kevin Ho: Affluent → Private on 15 May; Chen Wei: R3 → R4 on 5 Mar). A single static table would show today's segment on every past sale.
- **Design (same pattern as branch):**
  - `8_3nf_customer`: `cust_id_legacy` (the ID as the legacy systems hold it, zeros lost) next to the **rectified `cust_id`** (formula: trimmed and padded to 10 characters of text), which is the primary key; then name, dob, gender: facts that don't change.
  - `9_3nf_customer_history`: append-only change log, key = `cust_id + effective_date`, with segment and risk profile (101 versions). A new row only when either changes; `valid_to` is derived. Onboarding dates aren't in the log, so the first version uses an assumed date.
  - **Where this history comes from, and its scope:** segment and risk profile changes are derived from each customer's AUM (assets under management) and authorised by the bank, and the history is kept only for the customers who appear in the sales log (those who bought a product). A full history of every customer change across the bank would be far too large to maintain here, and it is sensitive data, so only what the sales reporting needs is kept (the data-minimisation principle).
- **Problem 1 fixed here:** the same rectification is applied to the log's `cust_id` in the enriched log, so 96 different raw IDs resolve to 80 customers. The enriched log carries only the rectified ID (no separate check column).
- **Enriched customer group:** rectified `cust_id` → name, dob, **`cust_age_at_sale`** (whole years between date of birth and the sale date, derived, never stored in the customer table because it changes every day), gender → `cust_info_since` → segment, risk profile (as of the sale date).
- **A real data-entry error surfaced:** T00308 (22 Apr) captured Maria Santos as "Affluent", but she was downgraded to "Mass" on 1 Mar. The history gives "Mass". This is exactly why segment shouldn't be typed onto each sale: the log's copy can be wrong, the reference can't drift.
- `1_raw_log` now has 12 columns: txn_id, txn_date_time, branch_code, product_code, cust_id, channel, campaign_code, currency, amount_local, fx_to_usd, sales_person_id, status.

### Customer ID rule, current view, and sheet order

- **One legacy variant:** the legacy system drops the leading `00` when an ID is stored as a number, so a raw ID is either 10 digits (correct) or 8 digits (lost `00`). The mock data follows this (59 sales arrive with 8 digits).
- **Rectify rule** (in `8_3nf_customer` and in the enriched log): 10 digits → keep; 8 digits → add `00` in front; any other length → **CHECK** (red), never guessed. All 80 customers and 500 sales rectify cleanly (0 CHECK).
- **`8_3nf_customer` also shows today's view:** current segment, current risk profile and `info_since`, calculated from the latest change in `9_3nf_customer_history` (like `5_branch`). The enriched log still uses the history for the values at the time of sale.
- **Sheet order:** numbered sheets are the ones that are finished (1 raw log … 9 customer history). `11_3nf_sales_person` is unnumbered and last because salesperson handling is not finished yet.

### Currency and FX: comparable amounts in HKD (`10_ref_fx_rate`)

- **Raw log keeps the facts of the sale:** `currency` and `amount_local`. `fx_to_usd` was removed: a rate is reference data, not a fact about a sale.
- **Currencies:** USD, HKD, CNY (RMB). The mock's earlier EUR sales were converted to CNY at the same value.
- **`10_ref_fx_rate`:** daily FX rates (USDHKD, USDCNY) **pulled from the Wind API / Bloomberg API**, one row per currency per business day (384 rows), key = `currency_code + rate_date`. Rates are stored the market way (units per 1 USD); `rate_to_hkd` = HKD per USD ÷ currency per USD on the same day. The feed only appends new days. (Values in this public mock are illustrative.)
- **Weekends and holidays have no rate,** so each sale uses the latest rate on or before its date: the same as-of lookup as the branch and customer histories. Example: a Saturday 18 Jan sale uses Friday 17 Jan's rate (33 weekend sales).
- **Enriched money group:** `currency` → `fx_rate_date` → `fx_rate_to_hkd` → **`amount_hkd`**, so all 500 sales are comparable in HKD, the bank's reporting currency.
- **Checks:** no duplicate rate keys, every sale finds a rate (PASS); all 500 HKD amounts match an independent calculation.

### Salesperson: reference table + confirmation workflow (`11_3nf_sales_person`, `12_sales_person_confirmation`)

- **Raw log:** only `sales_person_id`, the ID a salesperson types when signing the sale (a foreign key). Names live in `11_3nf_sales_person`.
- **Three outcomes for a typed ID:**
  - Valid → **OK**; differs only in case or spaces → **OK (auto-fixed)** (8 sales).
  - Blank → **SELF-DIRECTED** (109 sales).
  - Not a valid ID (14 sales) → logged in `12_sales_person_confirmation` for a person to resolve.
- **Confirmation workflow** (one row per flagged sale, keyed by `txn_id`): the sale's date, branch and typed ID are pulled automatically; a person records `action`, `confirmed_id`, `confirmed_by`, `confirmed_date`.
  - **Acknowledged:** the salesperson confirms the sale was theirs and gives their correct ID (7 sales).
  - **Corrected:** the operations team checks and assigns the right salesperson (3 sales).
  - Until all four fields are filled with a valid ID, the sale stays **PENDING** (4 sales) and is credited to no one. `E11` (could be E101 or E111) is never guessed.
- **Enriched salesperson group:** typed ID (cleaned) → `sales_person_check` → **`sales_person_id_corrected`** → `sales_person_name`. Confirmed sales automatically pick up the confirmed person.
- **Checks:** every flagged sale is logged (0 not logged); sales with a salesperson (387) + self-directed (109) + pending (4) = 500 (PASS). All confirmed IDs match the true salesperson in the mock data.
- **Why a separate table instead of overwriting the log:** the raw log stays exactly as signed (audit trail), and every correction records who decided and when.
- **Sheet order:** 1–10 as before, 11 salesperson, 12 confirmation, then notes.

### Principle: tables hold entities; checks live in one place (`13_checks`)

- A 3NF table describes its entity and nothing else. Counts like "sales in log for this branch" or "versions in history" are facts about the **log**, change every day, and were scattered across eight sheets. They were removed from every 3NF and reference table.
- Tables keep only their own data, their derived columns (`valid_to`, `is_current`, current name/segment) and short explanatory notes.
- `13_checks` holds all data-quality tests, one row each (area, check, violations, PASS / FAIL), re-running automatically as the log grows: key uniqueness and format, every foreign key resolving (date, time, branch version, product, customer, segment version, FX rate), no duplicate keys in history and FX tables, no orphan history rows, salesperson confirmations logged and complete.
- Pending confirmations show as **INFO**, not FAIL: they are expected work, not errors. Overall: ALL PASS (22 checks).
- **Tested by breaking it:** a copy with a duplicate txn_id, unknown branch, unknown product, 9-digit customer ID, duplicate FX rate and an unlogged typo made every relevant check FAIL. A check that can't fail proves nothing.
- In the SQL version these become automated data tests run on every load.

### Consistency review and fixes

- **Mock-data errors fixed:** gender now matches first names (38 customers had been assigned at random); a customer born in 2002 now onboards on his 18th birthday instead of at 17; 17 sales still "Pending" after weeks were settled (only sales from 16 Jun remain Pending).
- **Branch closures modelled:** a closure is a new version in `6_3nf_branch_history` with `branch_status = Closed` and a `successor_branch_code` (B05 → B02 from 1 Mar, B03 → B04 from 1 Jun). `5_branch` shows current status and successor; the enriched log shows `branch_status` as of each sale.
- **No duplicate column names:** cleaned keys in the enriched log are now `branch_code_std`, `product_code_std`, `cust_id_std`, `currency_std`, `sales_person_id_std` (needed for SQL).
- **Capacity made visible:** Excel formulas look at fixed ranges (branch history 50 rows, customer history 500, FX 2,000, calendar 400 days). Capacity checks in `13_checks` fail if a table outgrows its range; the SQL version has no such limit.
- **New checks:** no sale at a branch closed on the sale date; closed branches name an existing successor; customers are 18+ at onboarding. All three were confirmed to FAIL on a deliberately broken copy. Total: 28 checks, ALL PASS (4 pending confirmations as INFO).
- The `notes` tab was rewritten to match the current workbook.
- **Left as is by decision:** `channel`, `campaign_code`, `status` (system-generated) and salesperson employment history.

### Why a one big table (OBT) is the right final layer here

The enriched log is a one big table: every sale joined to its branch, product, customer, FX and salesperson information. For this project it is a clean design, not a shortcut:

- **One business process, one grain.** There is only one fact, sales at one row per sale. With nothing else sharing the dimensions, a star schema's main benefit, reusing (conforming) dimensions across several fact tables, doesn't apply yet.
- **The normalised tables stay the single source of truth.** The OBT is never typed into. Every descriptive column is a live lookup from the 3NF and reference tables, so a rename or a correction is made once, at the source, and flows through automatically. The update problems that make wide tables risky can't happen here.
- **History is already resolved correctly.** Each sale carries the exact version keys it was looked up with (`branch_info_since`, `cust_info_since`, `fx_rate_date`, the corrected salesperson ID), so every value can be traced back to one row in one table and shows the situation on the sale date, not today's.
- **It fits the consumers.** Excel users work best with one flat table for filters and pivots, and every check in `13_checks` validates it.
- **It is the place where new information is spotted.** When new sales arrive, every key is looked up, so anything the reference tables don't know yet shows immediately in red: a new customer (`cust_name` NOT FOUND), a new salesperson (`sales_person_check` CONFIRM), a new product or branch (NOT FOUND), a new currency or a date beyond the FX data (`fx_rate_date` NOT FOUND). The new information is then added once, to its 3NF table, and the OBT resolves automatically (and `13_checks` returns to PASS). This is the detect → data steward updates the reference → resolves loop, applied to every entity.
- **It is where existing information is extended into new factors.** My intuition is to derive new information from what is already there, so the same data can answer more business questions. Each derived column becomes a new way to slice the sales:
  - from the timestamp: year, quarter, month, ISO week, weekday, time of day → *when do customers buy?*
  - from date of birth + sale date: `cust_age_at_sale` → *which age groups buy which products?*
  - from currency + amount + daily FX: `amount_hkd` → *comparable totals across currencies*
  - from the salesperson ID: self-directed vs RM-assisted → *is the digital channel growing?*
  - from product risk vs customer risk at the time: a suitability flag → *are products sold within each customer's risk profile?*
  - from the branch history: branch status and name as of the sale → *performance before and after a rename or closure*

  These are derived, never typed: each is a formula over data that already exists, defined once in the OBT, so every report uses the same definition. In data science terms this is **feature engineering**; in warehouse terms, **derived attributes**.

**When it should be standardised into a fact table plus dimensions:** once a second process at a different grain arrives (e.g. monthly RM payouts or sales targets) that needs the same branch, customer and date dimensions; when a BI tool like Power BI is used, since it is designed around star schemas; or when data volume makes repeating descriptive columns on every row costly. The enriched log already contains everything needed for that step, because the version keys are exactly what a fact table would store.

## Is it a data warehouse? Evaluation against Inmon's four properties

| Property | Meaning | This workbook |
|---|---|---|
| **Subject-oriented** | Organised around a business subject, not an application | ✓ Retail wealth sales |
| **Integrated** | Different sources made consistent | ✓ Legacy customer IDs rectified, external daily FX feed (Wind / Bloomberg), one reporting currency (HKD), standardised `_std` keys |
| **Time-variant** | Keeps history, so data can be seen as it was | ✓ Append-only change logs for branch and customer, as-of-date lookups, daily FX rates |
| **Non-volatile** | Loaded data isn't changed; new data is appended | ◐ The raw log, change logs and FX table are append-only by design, but this is enforced by discipline, not by the system: the enriched log is live formulas, so editing a reference row instead of appending a new version would change past results |

**Layers:** staging (`1_raw_log`) → integration in 3NF with history (sheets 5–12) → analytical one big table (`2_enriched_log`) → data quality (`13_checks`).

**Conclusion:** it meets the design properties of a data warehouse for one subject, so it is a **data mart**: *an Excel prototype of a retail sales data mart, with warehouse-style layers, history and data-quality checks.* What separates it from a production warehouse is infrastructure rather than design: workbook storage instead of a database, pasted rather than scheduled loads (ETL), non-volatility by convention, and a single subject. The SQL version moves the same design onto a database.

## First report (`14_report`)

- **Rules applied to every chart (stated on the sheet):** Completed sales only · amounts in HKD millions via the daily FX rate · segment as at the time of sale · branches grouped by `branch_code` with today's name (closed branches marked) · refresh only when `13_checks` is ALL PASS.
- **Questions and findings (mock data, Jan–Jun 2025, HKD 564.6m completed):**
  1. *Is the business growing?* Monthly net sales range HKD 78m–113m, with no clear trend over six months; February is the peak (CNY campaign period).
  2. *What sells?* Deposits are the largest category and grew from Q1 (81m) to Q2 (97m); mutual funds and structured products dipped in Q2.
  3. *When do customers buy on their own?* All 30 evening and night sales are self-directed; RM-assisted sales happen only in the morning and afternoon.
  4. *Who buys?* Private customers bring 381m (67%) of net sales, Affluent 144m, Mass 40m.
  5. *Where?* Central (239m) and TST Harbour City (216m) dominate; closed Mong Kok and Shatin still show their sales before closure.
  6. *Suitability:* 8 completed sales (1.7%) were of a product riskier than the customer's risk profile at the time; shown as a headline number, not a chart.
- **Control total:** the report's total equals completed sales in the enriched log (PASS).
- **Chart design:** native Excel charts fed by small summary tables (live SUMIFS/COUNTIFS on the OBT); one colour per series in a fixed order (blue, orange), checked for colour-blind separation; value labels only where there are few bars.

## SQL version (PostgreSQL)

The same design, moved from a workbook onto a database. Nothing in the model changed; what changed is how each rule is enforced.

| Excel | PostgreSQL | What improves |
|---|---|---|
| Sheets | Schemas `raw`, `core`, `mart`, `dq` | Layers are separate namespaces with separate rights |
| Live formulas in the enriched log | Views (`core.sales_transaction` → `mart.sales_obt`) | Same "never typed into" property; no fixed ranges, no capacity limits |
| `MAXIFS` as-of lookups | `LEFT JOIN LATERAL (… ORDER BY effective_date DESC LIMIT 1)` | One definition, readable, indexed by the primary key |
| `IF(LEN=10, …, IF(LEN=8, "00"&…))` | Function `core.std_cust_id()`, also used in a `CHECK` on `core.customer` | The rule is written once and the table can't disagree with it |
| Uniqueness, format and lookup checks in `13_checks` | Primary keys, foreign keys, `CHECK` constraints | Bad reference data is rejected at the door instead of reported afterwards |
| Remaining checks (28 rows) | `dq.checks` (14 checks on the log) + `dq.summary` | Constraints cover the reference tables; checks cover what arrives in the log |
| Non-volatile by discipline | `etl` role has only `SELECT, INSERT` on `raw` | Non-volatile **enforced**: `UPDATE`, `DELETE`, `TRUNCATE` are refused |
| Pasting new rows | `src/load.py` (idempotent: `ON CONFLICT DO NOTHING`) | Re-runs never duplicate; a resolved confirmation is never overwritten |
| Saving a new workbook version | Alembic migrations 0001–0006, each reversible | Schema changes are versioned and can be rolled back |

**Why constraints don't replace every check.** The raw log must accept whatever the selling system sends, or sales would be lost at the door. So `raw.sales_log` has only a primary key, and its problems (unknown product, sale at a closed branch, mistyped salesperson) are reported by `dq.checks`, following the detect → data steward → resolve loop. Reference tables are maintained by people, so they are protected by constraints.

**Verification.** Loaded from the same data, the SQL version reproduces the workbook exactly: HKD 564.6m completed sales, every monthly, segment and branch total, 8 suitability flags, the same salesperson statuses (369 OK, 8 auto-fixed, 10 confirmed, 4 pending, 109 self-directed). A planted sale (unknown product and customer, booked to a closed branch) made four checks FAIL; `etl`'s attempts to update, delete or truncate the raw log were refused; `alembic downgrade base` followed by `upgrade head` rebuilt everything.

With non-volatility now enforced by the system, the Inmon evaluation above moves from ◐ to ✓ on all four properties.
