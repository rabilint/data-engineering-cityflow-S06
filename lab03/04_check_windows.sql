-- ГОТОВО. Виконати після створення ОБОХ віконних VIEW.
WITH expected AS (
 SELECT d.report_date,d.merchant_id,d.currency,d.order_amount,
        (SELECT SUM(p.order_amount) FROM lab03_cf.v_daily_orders p
         WHERE p.merchant_id=d.merchant_id AND p.currency=d.currency
           AND p.report_date<=d.report_date) AS cumulative_amount
 FROM lab03_cf.v_daily_orders d
), actual AS (
 SELECT report_date,merchant_id,currency,order_amount,cumulative_amount
 FROM lab03_cf.v_running_orders
), differences AS (
 (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)
 UNION ALL
 (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)
)
SELECT 'running_exact_match' AS check_name, COUNT(*) AS difference_rows,
       CASE WHEN COUNT(*)=0 THEN 'PASS' ELSE 'FAIL' END AS result FROM differences;
SELECT (SELECT COUNT(*) FROM lab03_cf.v_daily_orders) AS daily_rows,
       (SELECT COUNT(*) FROM lab03_cf.v_running_orders) AS running_rows;
-- Незалежна перевірка: не має існувати пізнішого замовлення цього клієнта.
WITH expected AS (
 SELECT o.customer_id,o.order_id,o.merchant_id,o.created_at,o.order_status,o.currency,o.total_amount
 FROM lab03_cf.v_period_orders o
 WHERE NOT EXISTS (
   SELECT 1 FROM lab03_cf.v_period_orders p
   WHERE p.customer_id=o.customer_id
     AND (p.created_at>o.created_at OR
         (p.created_at=o.created_at AND p.order_id>o.order_id))
 )
), actual AS (
 SELECT customer_id,order_id,merchant_id,created_at,order_status,currency,total_amount
 FROM lab03_cf.v_latest_customer_order
), differences AS (
 (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)
 UNION ALL
 (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)
)
SELECT 'latest_order_exact_match' AS check_name,COUNT(*) AS difference_rows,
       CASE WHEN COUNT(*)=0 THEN 'PASS' ELSE 'FAIL' END AS result FROM differences;
SELECT (SELECT COUNT(DISTINCT customer_id) FROM lab03_cf.v_period_orders) AS expected_customers,
       (SELECT COUNT(*) FROM lab03_cf.v_latest_customer_order) AS actual_rows;
