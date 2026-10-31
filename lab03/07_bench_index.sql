-- ГОТОВО. Запустити один раз після вимірів без індексу.
CREATE INDEX IF NOT EXISTS idx_lab03_cf_bench_merchant_created
ON lab03_cf.bench_orders (merchant_id, created_at);
ANALYZE lab03_cf.bench_orders;
SELECT indexname,indexdef FROM pg_indexes
WHERE schemaname='lab03_cf' AND tablename='bench_orders';
-- Далі знову 06_bench_query.sql: 1 прогрів та 3 вимірювання.
