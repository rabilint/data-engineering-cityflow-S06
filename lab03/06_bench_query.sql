-- ГОТОВО. Той самий файл ДО і ПІСЛЯ індексу; не змінюйте фільтр.
-- Один прогрів не враховуємо. Далі ще 3 виконання; записати Execution Time.
-- ANALYZE в EXPLAIN реально виконує SELECT. Не підставляйте UPDATE/DELETE.
EXPLAIN (ANALYZE, BUFFERS)
SELECT order_id, created_at, total_amount
FROM lab03_cf.bench_orders
WHERE merchant_id = (SELECT merchant_id FROM lab03_cf.bench_parameters)
  AND created_at >= (SELECT time_from FROM lab03_cf.bench_parameters)
  AND created_at <  (SELECT time_to FROM lab03_cf.bench_parameters);
