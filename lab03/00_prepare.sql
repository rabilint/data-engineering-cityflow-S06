-- ГОТОВО. Виконайте весь файл у навчальній БД з ЛР №2.
-- Читає core; створює тільки об'єкти lab03_cf. Старі lab03/lecture03 не зачіпає.
DO $$
BEGIN
  IF to_regclass('core.orders') IS NULL OR to_regclass('core.order_items') IS NULL THEN
    RAISE EXCEPTION 'Спочатку завершіть ЛР №2: потрібні core.orders та core.order_items.';
  END IF;
  PERFORM order_id, customer_id, merchant_id, created_at, order_status, currency, total_amount
  FROM core.orders LIMIT 1;
  PERFORM order_item_id, order_id, quantity FROM core.order_items LIMIT 1;
  IF NOT EXISTS (SELECT 1 FROM core.orders WHERE order_status = 'delivered') THEN
    RAISE EXCEPTION 'Немає delivered. Перевірте завантаження ЛР №2; не змінюйте статуси для обходу.';
  END IF;
END $$;
CREATE SCHEMA IF NOT EXISTS lab03_cf;
CREATE TABLE IF NOT EXISTS lab03_cf.settings (
  id integer PRIMARY KEY CHECK (id = 1),
  date_from date NOT NULL,
  date_to date NOT NULL,
  CHECK (date_to > date_from)
);
-- Обираємо перший календарний місяць, де є delivered, у Europe/Kyiv.
-- Параметри зберігаються: повторний запуск не переобирає місяць.
WITH first_month AS (
  SELECT date_trunc('month', MIN(created_at AT TIME ZONE 'Europe/Kyiv')) AS m
  FROM core.orders WHERE order_status = 'delivered'
)
INSERT INTO lab03_cf.settings (id, date_from, date_to)
SELECT 1, m::date, (m + INTERVAL '1 month')::date FROM first_month
ON CONFLICT (id) DO NOTHING;
-- VIEW — збережений SELECT, а не нове завантаження чи копія core.
-- Тут усі статуси; delivered ви оберете у власному денному звіті.
CREATE OR REPLACE VIEW lab03_cf.v_period_orders AS
SELECT o.order_id, o.customer_id, o.merchant_id, o.created_at,
       o.order_status, o.currency, o.total_amount,
       (o.created_at AT TIME ZONE 'Europe/Kyiv')::date AS report_date
FROM core.orders o CROSS JOIN lab03_cf.settings p
WHERE o.created_at >= (p.date_from::timestamp AT TIME ZONE 'Europe/Kyiv')
  AND o.created_at <  (p.date_to::timestamp AT TIME ZONE 'Europe/Kyiv');
SELECT date_from, date_to, 'Europe/Kyiv' AS report_timezone FROM lab03_cf.settings;
SELECT order_status, currency, COUNT(*) AS orders, SUM(total_amount) AS amount
FROM lab03_cf.v_period_orders GROUP BY order_status, currency ORDER BY order_status, currency;
SELECT COUNT(*) AS accepted_orders FROM core.orders;
SELECT COUNT(*) AS accepted_items FROM core.order_items;
