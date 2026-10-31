-- ГОТОВО. Порівняння набору рядків, а не їхнього порядку.
WITH after_index AS (SELECT order_id, created_at, total_amount
FROM lab03_cf.bench_orders
WHERE merchant_id = (SELECT merchant_id FROM lab03_cf.bench_parameters)
  AND created_at >= (SELECT time_from FROM lab03_cf.bench_parameters)
  AND created_at <  (SELECT time_to FROM lab03_cf.bench_parameters)), differences AS (
  (SELECT * FROM lab03_cf.bench_before EXCEPT ALL SELECT * FROM after_index)
  UNION ALL
  (SELECT * FROM after_index EXCEPT ALL SELECT * FROM lab03_cf.bench_before)
)
SELECT 'benchmark_same_result' AS check_name,COUNT(*) AS difference_rows,
       CASE WHEN COUNT(*)=0 THEN 'PASS' ELSE 'FAIL' END AS result FROM differences;
