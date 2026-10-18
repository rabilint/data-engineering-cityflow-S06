-- ==============================================================================
-- Лабораторна робота 2: Створення таблиць staging (stg)
-- ==============================================================================
-- Принципи staging-рівня:
-- 1. Бізнес-поля приймаються як TEXT без обмежень типів, щоб уникнути втрати записів.
-- 2. Без обмежень первинних/зовнішніх ключів або унікальності (PK, FK, UNIQUE),
--    щоб успішно прийняти дублікати, некоректні ключі та "брудні" дані.
-- 3. Обов'язкові технічні метадані:
--    - batch_id          : унікальний ідентифікатор пакету завантаження
--    - source_file       : назва/шлях вихідного файлу
--    - source_row_number : порядковий номер рядка в CSV після заголовка (1-based)
--    - loaded_at         : точна мітка часу завантаження (TIMESTAMPTZ)
-- ==============================================================================

-- 1. Таблиця stg.customers (джерело: base/customers.csv)
CREATE TABLE IF NOT EXISTS stg.customers (
    -- Технічні метадані
    batch_id VARCHAR(64) NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number BIGINT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    
    -- Вихідні поля з CSV (усі як TEXT)
    customer_id TEXT,
    full_name TEXT,
    email TEXT,
    phone TEXT,
    city TEXT,
    service_zone_id TEXT,
    registered_at TEXT,
    customer_status TEXT
);

-- 2. Таблиця stg.merchants (джерело: base/merchants.csv)
CREATE TABLE IF NOT EXISTS stg.merchants (
    batch_id VARCHAR(64) NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number BIGINT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    
    merchant_id TEXT,
    merchant_name TEXT,
    merchant_type TEXT,
    city TEXT,
    service_zone_id TEXT,
    opened_at TEXT,
    merchant_status TEXT
);

-- 3. Таблиця stg.products (джерело: base/products.csv)
CREATE TABLE IF NOT EXISTS stg.products (
    batch_id VARCHAR(64) NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number BIGINT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    
    product_id TEXT,
    merchant_id TEXT,
    product_name TEXT,
    category TEXT,
    unit_price_uah TEXT,
    is_active TEXT,
    updated_at TEXT
);

-- 4. Таблиця stg.orders (джерело: base/orders.csv)
CREATE TABLE IF NOT EXISTS stg.orders (
    batch_id VARCHAR(64) NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number BIGINT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    
    order_id TEXT,
    customer_id TEXT,
    merchant_id TEXT,
    created_at TEXT,
    order_status TEXT,
    currency TEXT,
    subtotal_amount TEXT,
    delivery_fee TEXT,
    discount_amount TEXT,
    total_amount TEXT
);

-- 5. Таблиця stg.order_items (джерело: relational/order_items.csv)
CREATE TABLE IF NOT EXISTS stg.order_items (
    batch_id VARCHAR(64) NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number BIGINT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    
    order_item_id TEXT,
    order_id TEXT,
    product_id TEXT,
    quantity TEXT,
    unit_price TEXT,
    line_discount TEXT,
    line_total TEXT,
    currency TEXT
);

-- Додаткові таблиці розширення реляційного пакету (data/raw/relational)

-- 6. Таблиця stg.couriers
CREATE TABLE IF NOT EXISTS stg.couriers (
    batch_id VARCHAR(64) NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number BIGINT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    
    courier_id TEXT,
    full_name TEXT,
    city TEXT,
    home_service_zone_id TEXT,
    hired_at TEXT,
    courier_status TEXT,
    vehicle_type TEXT
);

-- 7. Таблиця stg.deliveries
CREATE TABLE IF NOT EXISTS stg.deliveries (
    batch_id VARCHAR(64) NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number BIGINT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    
    delivery_id TEXT,
    order_id TEXT,
    courier_id TEXT,
    service_zone_id TEXT,
    assigned_at TEXT,
    picked_up_at TEXT,
    delivered_at TEXT,
    delivery_status TEXT,
    sla_minutes TEXT,
    distance_km TEXT,
    actual_delivery_minutes TEXT,
    delay_minutes TEXT
);

-- 8. Таблиця stg.payments
CREATE TABLE IF NOT EXISTS stg.payments (
    batch_id VARCHAR(64) NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number BIGINT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    
    payment_id TEXT,
    order_id TEXT,
    payment_method TEXT,
    payment_status TEXT,
    authorized_at TEXT,
    captured_at TEXT,
    amount TEXT,
    currency TEXT,
    provider_reference TEXT
);

-- 9. Таблиця stg.refunds
CREATE TABLE IF NOT EXISTS stg.refunds (
    batch_id VARCHAR(64) NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number BIGINT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    
    refund_id TEXT,
    payment_id TEXT,
    order_id TEXT,
    refund_type TEXT,
    refund_status TEXT,
    amount TEXT,
    currency TEXT,
    reason TEXT,
    requested_at TEXT,
    completed_at TEXT
);

-- 10. Таблиця stg.service_zones
CREATE TABLE IF NOT EXISTS stg.service_zones (
    batch_id VARCHAR(64) NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number BIGINT NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    
    service_zone_id TEXT,
    city TEXT,
    zone_name TEXT,
    base_delivery_fee_uah TEXT,
    sla_minutes TEXT,
    traffic_factor TEXT,
    timezone TEXT
);

-- Індекси на метадані для швидкої вибірки по пакетах завантаження
CREATE INDEX IF NOT EXISTS idx_stg_customers_batch ON stg.customers(batch_id);
CREATE INDEX IF NOT EXISTS idx_stg_merchants_batch ON stg.merchants(batch_id);
CREATE INDEX IF NOT EXISTS idx_stg_products_batch ON stg.products(batch_id);
CREATE INDEX IF NOT EXISTS idx_stg_orders_batch ON stg.orders(batch_id);
CREATE INDEX IF NOT EXISTS idx_stg_order_items_batch ON stg.order_items(batch_id);
