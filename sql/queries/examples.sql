-- Example queries against bank_sales. Run in DBeaver / pgAdmin / psql.

-- 1. Health first: never report on data that fails its checks.
SELECT * FROM dq.summary;
SELECT * FROM dq.checks WHERE result <> 'PASS';

-- 2. History resolved as of the sale date: the same customer in different segments over time.
SELECT cust_id, cust_name, txn_date, cust_info_since, cust_segment, cust_risk_profile
FROM mart.sales_obt
WHERE cust_id IN (SELECT cust_id FROM core.customer_history GROUP BY cust_id HAVING count(*) > 1)
ORDER BY cust_id, txn_date
LIMIT 20;

-- 3. Branch closures: sales before closure keep the branch's own name and status.
SELECT branch_code, branch_name, branch_status, min(txn_date) AS first_sale, max(txn_date) AS last_sale, count(*) AS sales
FROM mart.sales_obt
GROUP BY branch_code, branch_name, branch_status
ORDER BY branch_code;

-- 4. Data steward's to-do list: salesperson IDs waiting for confirmation.
SELECT txn_id, txn_date, branch_code, sales_person_id_typed, sales_person_check
FROM mart.sales_obt
WHERE sales_person_check IN ('PENDING CONFIRM', 'CONFIRM (not logged)')
ORDER BY txn_date;

-- 5. Suitability detail: products riskier than the customer's profile at the time of sale.
SELECT txn_id, txn_date, cust_name, cust_risk_profile, product_name, product_risk_level, round(amount_hkd) AS amount_hkd
FROM mart.sales_obt
WHERE status = 'Completed'
  AND product_risk_level > cust_risk_profile   -- R1..R5 compare correctly as text
ORDER BY txn_date;

-- 6. Derived attributes at work: which age groups buy which product categories?
SELECT width_bucket(cust_age_at_sale, 20, 80, 6) AS age_band,
       min(cust_age_at_sale) || '-' || max(cust_age_at_sale) AS ages,
       product_category,
       round(sum(amount_hkd) / 1e6, 1) AS net_sales_hkd_m
FROM mart.sales_obt
WHERE status = 'Completed'
GROUP BY 1, 3
ORDER BY 1, 4 DESC;
