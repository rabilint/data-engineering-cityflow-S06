-- ==============================================================================
-- Лабораторна робота 2: Альтернативний імпорт через psql \copy
-- ==============================================================================
-- Цей скрипт демонструє завантаження джерел безпосередньо через psql CLI.
-- Зверніть увагу: перед запуском шляхи до файлів мають бути абсолютними
-- або запускатися з кореневої директорії проекту.
-- ==============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- 1. Створення пакету в аудиті
\set batch_id 'batch_psql_copy_':CURRENT_DATE
INSERT INTO audit.load_batches (batch_id, started_at, status)
VALUES (:'batch_id', clock_timestamp(), 'RUNNING')
ON CONFLICT (batch_id) DO UPDATE SET started_at = clock_timestamp(), status = 'RUNNING';

-- 2. Завантаження customers
\copy stg.customers(customer_id, full_name, email, phone, city, service_zone_id, registered_at, customer_status) FROM 'data/raw/base/customers.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

UPDATE stg.customers
SET batch_id = :'batch_id',
    source_file = 'customers.csv',
    loaded_at = clock_timestamp()
WHERE batch_id IS NULL;

-- 3. Завантаження merchants
\copy stg.merchants(merchant_id, merchant_name, merchant_type, city, service_zone_id, opened_at, merchant_status) FROM 'data/raw/base/merchants.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

UPDATE stg.merchants
SET batch_id = :'batch_id',
    source_file = 'merchants.csv',
    loaded_at = clock_timestamp()
WHERE batch_id IS NULL;

-- 4. Завантаження products
\copy stg.products(product_id, merchant_id, product_name, category, unit_price_uah, is_active, updated_at) FROM 'data/raw/base/products.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

UPDATE stg.products
SET batch_id = :'batch_id',
    source_file = 'products.csv',
    loaded_at = clock_timestamp()
WHERE batch_id IS NULL;

-- 5. Завантаження orders
\copy stg.orders(order_id, customer_id, merchant_id, created_at, order_status, currency, subtotal_amount, delivery_fee, discount_amount, total_amount) FROM 'data/raw/base/orders.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

UPDATE stg.orders
SET batch_id = :'batch_id',
    source_file = 'orders.csv',
    loaded_at = clock_timestamp()
WHERE batch_id IS NULL;

-- 6. Завантаження order_items
\copy stg.order_items(order_item_id, order_id, product_id, quantity, unit_price, line_discount, line_total, currency) FROM 'data/raw/relational/order_items.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

UPDATE stg.order_items
SET batch_id = :'batch_id',
    source_file = 'order_items.csv',
    loaded_at = clock_timestamp()
WHERE batch_id IS NULL;

-- Завершення пакету в аудиті
UPDATE audit.load_batches
SET status = 'SUCCESS', completed_at = clock_timestamp()
WHERE batch_id = :'batch_id';

COMMIT;
