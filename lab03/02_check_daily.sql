-- ГОТОВО. Виконувати після створення v_daily_orders.
-- Еталон нижче: незалежний підрахунок за кожним замовленням без множення JOIN.
WITH expected AS (
  SELECT o.report_date, o.merchant_id, o.currency,
         COUNT(*) AS order_count, SUM(o.total_amount) AS order_amount,
         ROUND(AVG(o.total_amount), 2) AS avg_order_amount,
         SUM(COALESCE((SELECT SUM(i.quantity) FROM core.order_items i
                        WHERE i.order_id = o.order_id), 0)) AS accepted_units,
         COUNT(*) FILTER (WHERE NOT EXISTS
             (SELECT 1 FROM core.order_items i WHERE i.order_id = o.order_id)) AS orders_without_items
  FROM lab03_cf.v_period_orders o WHERE o.order_status = 'delivered'
  GROUP BY o.report_date, o.merchant_id, o.currency
), actual AS (
  SELECT report_date, merchant_id, currency, order_count, order_amount,
         avg_order_amount, accepted_units, orders_without_items
  FROM lab03_cf.v_daily_orders
), differences AS (
  (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)
  UNION ALL
  (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected)
)
SELECT 'daily_exact_match' AS check_name, COUNT(*) AS difference_rows,
       CASE WHEN COUNT(*)=0 THEN 'PASS' ELSE 'FAIL' END AS result FROM differences;
-- EXCEPT ALL зберігає кратність повторів: дубльований рядок теж буде помилкою.
-- Звірка за валютою. Нулі в обох difference_* означають узгодженість.
WITH source AS (
 SELECT currency, COUNT(*) AS cnt, SUM(total_amount) AS amt
 FROM lab03_cf.v_period_orders WHERE order_status='delivered' GROUP BY currency
), report AS (
 SELECT currency, SUM(order_count) AS cnt, SUM(order_amount) AS amt
 FROM lab03_cf.v_daily_orders GROUP BY currency
)
SELECT COALESCE(s.currency,r.currency) AS currency,
       s.cnt AS source_orders, r.cnt AS report_orders,
       s.amt AS source_amount, r.amt AS report_amount,
       COALESCE(r.cnt,0)-COALESCE(s.cnt,0) AS difference_count,
       COALESCE(r.amt,0)-COALESCE(s.amt,0) AS difference_amount
FROM source s FULL JOIN report r USING(currency) ORDER BY currency;
