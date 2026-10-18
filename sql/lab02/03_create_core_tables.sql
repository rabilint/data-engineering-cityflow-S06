-- ==============================================================================
-- Лабораторна робота 2: Створення таблиць ядра (core)
-- ==============================================================================
-- Принципи core-рівня:
-- 1. Тільки валідовані, типізовані бізнес-дані (DWH / Relational Core).
-- 2. Суворі обмеження цілісності: PRIMARY KEY, FOREIGN KEY, NOT NULL, CHECK.
-- 3. Реалізація мінімального переліку полів згідно з вимогами.
--    Решта полів (як-от phone, customer_status, service_zone_id тощо)
--    зберігається у staging (stg) для запобігання втрати первинного контексту.
-- 4. ВАЖЛИВО: Email НЕ оголошується унікальним (UNIQUE) без підтвердженого
--    бізнес-правила (в сирих даних кілька клієнтів мають спільну пошту,
--    наприклад спільні сімейні акаунти, тому обмеження UNIQUE призведе до збою).
-- ==============================================================================

-- 1. Клієнти (customers)
CREATE TABLE IF NOT EXISTS core.customers (
    customer_id VARCHAR(64) PRIMARY KEY,
    full_name VARCHAR(255) NOT NULL,
    city VARCHAR(100) NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL
);

-- Коментар: якщо email додається до розширеного core, він не повинен мати UNIQUE constraint:
-- ALTER TABLE core.customers ADD COLUMN IF NOT EXISTS email VARCHAR(255); -- БЕЗ UNIQUE!

-- 2. Заклади / Мерчанти (merchants)
CREATE TABLE IF NOT EXISTS core.merchants (
    merchant_id VARCHAR(64) PRIMARY KEY,
    merchant_name VARCHAR(255) NOT NULL,
    city VARCHAR(100) NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL
);

-- 3. Товари (products)
CREATE TABLE IF NOT EXISTS core.products (
    product_id VARCHAR(64) PRIMARY KEY,
    merchant_id VARCHAR(64) NOT NULL REFERENCES core.merchants(merchant_id),
    product_name VARCHAR(255) NOT NULL,
    unit_price_uah NUMERIC(12, 2) NOT NULL CHECK (unit_price_uah >= 0),
    is_active BOOLEAN NOT NULL DEFAULT true
);

-- 4. Замовлення (orders)
CREATE TABLE IF NOT EXISTS core.orders (
    order_id VARCHAR(64) PRIMARY KEY,
    customer_id VARCHAR(64) NOT NULL REFERENCES core.customers(customer_id),
    merchant_id VARCHAR(64) NOT NULL REFERENCES core.merchants(merchant_id),
    created_at TIMESTAMPTZ NOT NULL,
    order_status VARCHAR(50) NOT NULL,
    currency VARCHAR(10) NOT NULL CHECK (currency IN ('UAH', 'USD', 'EUR')),
    subtotal_amount NUMERIC(12, 2) NOT NULL CHECK (subtotal_amount >= 0),
    delivery_fee NUMERIC(12, 2) DEFAULT 0.00 CHECK (delivery_fee IS NULL OR delivery_fee >= 0),
    discount_amount NUMERIC(12, 2) DEFAULT 0.00 CHECK (discount_amount IS NULL OR discount_amount >= 0),
    total_amount NUMERIC(12, 2) NOT NULL CHECK (total_amount >= 0)
);

-- 5. Позиції замовлення (order_items)
CREATE TABLE IF NOT EXISTS core.order_items (
    order_item_id VARCHAR(64) PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL REFERENCES core.orders(order_id) ON DELETE CASCADE,
    product_id VARCHAR(64) NOT NULL REFERENCES core.products(product_id),
    quantity INT NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0),
    line_discount NUMERIC(12, 2) DEFAULT 0.00 CHECK (line_discount IS NULL OR line_discount >= 0),
    line_total NUMERIC(12, 2) NOT NULL CHECK (line_total >= 0),
    currency VARCHAR(10) NOT NULL CHECK (currency IN ('UAH', 'USD', 'EUR'))
);

-- Індекси для забезпечення високої швидкості об'єднань (JOIN)
CREATE INDEX IF NOT EXISTS idx_core_products_merchant_id ON core.products(merchant_id);
CREATE INDEX IF NOT EXISTS idx_core_orders_customer_id ON core.orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_core_orders_merchant_id ON core.orders(merchant_id);
CREATE INDEX IF NOT EXISTS idx_core_orders_created_at ON core.orders(created_at);
CREATE INDEX IF NOT EXISTS idx_core_order_items_order_id ON core.order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_core_order_items_product_id ON core.order_items(product_id);
