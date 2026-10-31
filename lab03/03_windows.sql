-- СТУДЕНТ. Напишіть два VIEW на вже наявних даних CityFlow.
-- 1. lab03_cf.v_running_orders:
-- report_date, merchant_id, currency, order_amount, cumulative_amount.
-- Джерело v_daily_orders. Збережіть всі його денні рядки.
-- Використайте SUM(order_amount) OVER (
--   PARTITION BY merchant_id, currency ORDER BY report_date
--   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
-- ). Календар з порожніми днями не створюйте.
-- TODO: ваш CREATE OR REPLACE VIEW ...

CREATE OR REPLACE VIEW lab03_cf.v_running_orders AS
SELECT
  report_date,
  merchant_id,
  currency,
  order_amount,
  SUM(order_amount) OVER (
    PARTITION BY merchant_id, currency
    ORDER BY report_date
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
  ) AS cumulative_amount
FROM lab03_cf.v_daily_orders;

-- 2. lab03_cf.v_latest_customer_order:
-- customer_id, order_id, merchant_id, created_at, order_status, currency, total_amount.
-- Джерело v_period_orders, УСІ статуси вибраного місяця.
-- Пронумеруйте замовлення ROW_NUMBER() OVER (
--   PARTITION BY customer_id ORDER BY created_at DESC, order_id DESC
-- ). У зовнішньому SELECT залиште rn=1.
-- order_id розв'язує нічию детерміновано; не означає версію статусу.
-- Це останнє створене замовлення клієнта в місяці, а не історія одного замовлення.
-- TODO: ваш CREATE OR REPLACE VIEW ...
CREATE OR REPLACE VIEW lab03_cf.v_latest_customer_order AS
WITH ranked_orders AS (
  SELECT
    customer_id,
    order_id,
    merchant_id,
    created_at,
    order_status,
    currency,
    total_amount,
    ROW_NUMBER() OVER (
      PARTITION BY customer_id
      ORDER BY created_at DESC, order_id DESC
    ) AS rn
  FROM lab03_cf.v_period_orders
)
SELECT
  customer_id,
  order_id,
  merchant_id,
  created_at,
  order_status,
  currency,
  total_amount
FROM ranked_orders
WHERE rn = 1;

-- Після створення прочитайте:
-- SELECT * FROM lab03_cf.v_running_orders ORDER BY merchant_id,currency,report_date;
-- SELECT * FROM lab03_cf.v_latest_customer_order ORDER BY customer_id;

SELECT * FROM lab03_cf.v_running_orders ORDER BY merchant_id, currency, report_date;
SELECT * FROM lab03_cf.v_latest_customer_order ORDER BY customer_id;