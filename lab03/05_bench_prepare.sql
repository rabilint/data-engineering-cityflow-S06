-- ГОТОВО. Лише спеціальні копії lab03_cf.bench_* будуть перестворені.
-- Не виконуйте посеред вимірювань. DROP без CASCADE; core не змінюється.
DROP TABLE IF EXISTS lab03_cf.bench_before;
DROP TABLE IF EXISTS lab03_cf.bench_orders;
DROP TABLE IF EXISTS lab03_cf.bench_parameters;
CREATE TABLE lab03_cf.bench_orders AS
SELECT order_id,merchant_id,created_at,total_amount FROM core.orders;
-- CREATE TABLE AS не копіює індекси core.orders.
-- Вибираємо заклад із найбільшою кількістю замовлень у місяці; всі статуси.
CREATE TABLE lab03_cf.bench_parameters AS
SELECT m.merchant_id,
       p.date_from::timestamp AT TIME ZONE 'Europe/Kyiv' AS time_from,
       p.date_to::timestamp AT TIME ZONE 'Europe/Kyiv' AS time_to
FROM lab03_cf.settings p CROSS JOIN (
 SELECT merchant_id FROM lab03_cf.v_period_orders
 GROUP BY merchant_id ORDER BY COUNT(*) DESC,merchant_id LIMIT 1
) m;
ANALYZE lab03_cf.bench_orders;

CREATE TABLE lab03_cf.bench_before AS SELECT order_id, created_at, total_amount
FROM lab03_cf.bench_orders
WHERE merchant_id = (SELECT merchant_id FROM lab03_cf.bench_parameters)
  AND created_at >= (SELECT time_from FROM lab03_cf.bench_parameters)
  AND created_at <  (SELECT time_to FROM lab03_cf.bench_parameters);
SELECT * FROM lab03_cf.bench_parameters;
SELECT COUNT(*) AS benchmark_rows FROM lab03_cf.bench_orders;
SELECT COUNT(*) AS matching_rows FROM lab03_cf.bench_before;
SELECT indexname,indexdef FROM pg_indexes
WHERE schemaname='lab03_cf' AND tablename='bench_orders';
-- Останній результат: 0 індексів. Числа залежать від вашого core.
