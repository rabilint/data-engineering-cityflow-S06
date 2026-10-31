-- СТУДЕНТ. Блок А: виконайте три порівняння. Два останні — НАВМИСНО неправильні.
SELECT currency, COUNT(*) AS orders, SUM(total_amount) AS correct_amount
FROM lab03_cf.v_period_orders WHERE order_status = 'delivered'
GROUP BY currency ORDER BY currency;

SELECT o.currency, COUNT(*) AS joined_rows, SUM(o.total_amount) AS wrong_amount
FROM lab03_cf.v_period_orders o JOIN core.order_items i ON i.order_id = o.order_id
WHERE o.order_status = 'delivered' GROUP BY o.currency ORDER BY o.currency;

SELECT o.currency, SUM(DISTINCT o.total_amount) AS not_a_valid_fix
FROM lab03_cf.v_period_orders o JOIN core.order_items i ON i.order_id = o.order_id
WHERE o.order_status = 'delivered' GROUP BY o.currency ORDER BY o.currency;

SELECT o.order_id, o.currency, o.total_amount, COUNT(i.order_item_id) AS item_rows, SUM(i.quantity) AS total_units
FROM lab03_cf.v_period_orders o LEFT JOIN core.order_items i ON o.order_id = i.order_id
WHERE o.order_id IN ('S06-O0000001', 'S06-O0000002', 'S06-O0000003')
GROUP BY o.order_id, o.currency, o.total_amount ORDER BY o.order_id;

-- Блок Б: допишіть CREATE OR REPLACE VIEW lab03_cf.v_daily_orders AS ...
-- Не змінюйте core та v_period_orders. Приклад першого CTE:
WITH items_by_order AS (
  SELECT order_id, SUM(quantity) AS units
  FROM core.order_items GROUP BY order_id
)
SELECT * FROM items_by_order ORDER BY order_id LIMIT 10;

CREATE OR REPLACE VIEW lab03_cf.v_daily_orders AS
WITH selected_orders AS (
  SELECT order_id, merchant_id, currency, total_amount, report_date
  FROM lab03_cf.v_period_orders
  WHERE order_status = 'delivered'
),
items_by_order AS (
  SELECT order_id, SUM(quantity) AS units
  FROM core.order_items
  GROUP BY order_id
),
orders_with_units AS (
  SELECT o.order_id,
         o.merchant_id,
         o.currency,
         o.total_amount,
         o.report_date,
         COALESCE(i.units, 0) AS units,
         CASE WHEN i.order_id IS NULL THEN 1 ELSE 0 END AS is_without_items
  FROM selected_orders o
  LEFT JOIN items_by_order i ON o.order_id = i.order_id
)
SELECT
  report_date,
  merchant_id,
  currency,
  COUNT(*)::bigint AS order_count,
  SUM(total_amount) AS order_amount,
  ROUND(SUM(total_amount) / COUNT(*), 2) AS avg_order_amount,
  SUM(units)::bigint AS accepted_units,
  SUM(is_without_items)::bigint AS orders_without_items
FROM orders_with_units
GROUP BY report_date, merchant_id, currency;

-- TODO: 3 CTE у ВАШОМУ запиті:
-- selected_orders: v_period_orders WHERE order_status = 'delivered';
-- items_by_order: один рядок на order_id, сума quantity;
-- orders_with_units: LEFT JOIN selected_orders з items_by_order за order_id.
-- Відсутній units -> COALESCE(units, 0). Відсутнє i.order_id -> ознака без позицій.
-- GROUP BY report_date, merchant_id, currency.
-- Порядок вихідних колонок:
-- report_date, merchant_id, currency, order_count, order_amount,
-- avg_order_amount, accepted_units, orders_without_items.
-- Типи: date, text, text, bigint, numeric, numeric, bigint/numeric, bigint.
-- Правила п'яти метрик наведені в завданні. Створіть VIEW, а не таблицю.
-- Приклад читання ПІСЛЯ створення:
-- SELECT * FROM lab03_cf.v_daily_orders ORDER BY report_date, merchant_id, currency;

SELECT * FROM lab03_cf.v_daily_orders ORDER BY report_date, merchant_id, currency;
