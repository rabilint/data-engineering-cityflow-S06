-- ==============================================================================
-- Лабораторна робота 2 (Завдання 4): Правила приймання та трансформація STG -> CORE
-- ==============================================================================
-- Цей SQL-скрипт реалізує навчальний контракт приймання даних із stg.* у core.*:
-- 1. Типізація та перевірка порожніх/некоректних ключів і дат.
-- 2. Нормалізація регістру та пробілів, парсинг дат (ISO 8601 та DD/MM/YYYY HH:MM як UTC).
-- 3. Валідація валют ('UAH', 'USD', 'EUR') без виправлення 'UA H'.
-- 4. Перевірка цін: активні товари з ціною <= 0 відхиляються.
-- 5. Дедуплікація точних бізнес-копій (1 залишається, решта в duplicate).
-- 6. Конфліктні ключі з різними бізнес-значеннями відхиляються всією групою.
-- 7. Перевірка зовнішніх ключів (FK): замовлення та позиції до відхилених батьків
--    фіксуються в audit.rejected_records і не потрапляють у core.
-- ==============================================================================

BEGIN;

-- Змінна batch_id (останній успішний пакет у staging)
DO $$
DECLARE
    v_batch_id VARCHAR(64);
BEGIN
    SELECT batch_id INTO v_batch_id
    FROM audit.load_batches
    WHERE status = 'SUCCESS'
    ORDER BY completed_at DESC
    LIMIT 1;

    IF v_batch_id IS NULL THEN
        RAISE EXCEPTION 'Не знайдено жодного успішного batch у audit.load_batches';
    END IF;

    -- Очищення попередніх даних у core для уникнення конфліктів
    TRUNCATE TABLE core.order_items, core.orders, core.products, core.customers, core.merchants CASCADE;
    DELETE FROM audit.rejected_records WHERE batch_id = v_batch_id;

    -- --------------------------------------------------------------------------
    -- 1. CUSTOMERS
    -- --------------------------------------------------------------------------
    -- 1.1. Фіксація дублікатів та конфліктних груп у audit.rejected_records
    INSERT INTO audit.rejected_records (batch_id, source_table, source_row_number, entity_id, rejection_reason, details)
    SELECT 
        v_batch_id, 'stg.customers', source_row_number, customer_id,
        CASE 
            WHEN count(DISTINCT (trim(full_name), trim(email), trim(coalesce(phone, '')), trim(city), trim(service_zone_id), trim(registered_at), trim(customer_status))) OVER (PARTITION BY trim(customer_id)) > 1
            THEN 'KEY_CONFLICT_DIFFERENT_VALUES'
            ELSE 'DUPLICATE_BUSINESS_COPY'
        END,
        CASE 
            WHEN count(DISTINCT (trim(full_name), trim(email), trim(coalesce(phone, '')), trim(city), trim(service_zone_id), trim(registered_at), trim(customer_status))) OVER (PARTITION BY trim(customer_id)) > 1
            THEN 'Customer has conflicting values across rows without authoritative version'
            ELSE 'Exact duplicate business copy of customer'
        END
    FROM stg.customers
    WHERE batch_id = v_batch_id
      AND customer_id IS NOT NULL AND trim(customer_id) != ''
      AND customer_id IN (SELECT customer_id FROM stg.customers WHERE batch_id = v_batch_id GROUP BY customer_id HAVING count(*) > 1)
      -- Якщо це точна копія, залишаємо рядок з найменшим source_row_number, а решту логуємо як дублікати
      AND (
          count(DISTINCT (trim(full_name), trim(email), trim(coalesce(phone, '')), trim(city), trim(service_zone_id), trim(registered_at), trim(customer_status))) OVER (PARTITION BY trim(customer_id)) > 1
          OR row_number() OVER (PARTITION BY trim(customer_id) ORDER BY source_row_number) > 1
      );

    -- 1.2. Вставка валідних клієнтів у core.customers
    INSERT INTO core.customers (customer_id, full_name, city, registered_at)
    SELECT 
        trim(customer_id),
        trim(full_name),
        trim(city),
        registered_at::timestamptz
    FROM (
        SELECT *,
            row_number() OVER (PARTITION BY trim(customer_id) ORDER BY source_row_number) as rn,
            count(DISTINCT (trim(full_name), trim(email), trim(coalesce(phone, '')), trim(city), trim(service_zone_id), trim(registered_at), trim(customer_status))) OVER (PARTITION BY trim(customer_id)) as diff_count
        FROM stg.customers
        WHERE batch_id = v_batch_id
          AND customer_id IS NOT NULL AND trim(customer_id) != ''
    ) sub
    WHERE diff_count = 1 AND rn = 1;

    -- --------------------------------------------------------------------------
    -- 2. MERCHANTS
    -- --------------------------------------------------------------------------
    -- 2.1. Фіксація дублікатів та конфліктів
    INSERT INTO audit.rejected_records (batch_id, source_table, source_row_number, entity_id, rejection_reason, details)
    SELECT 
        v_batch_id, 'stg.merchants', source_row_number, merchant_id,
        'DUPLICATE_BUSINESS_COPY',
        'Exact duplicate business copy of merchant'
    FROM (
        SELECT *,
            row_number() OVER (PARTITION BY trim(merchant_id) ORDER BY source_row_number) as rn
        FROM stg.merchants
        WHERE batch_id = v_batch_id
    ) sub
    WHERE rn > 1;

    -- 2.2. Вставка валідних мерчантів у core.merchants
    INSERT INTO core.merchants (merchant_id, merchant_name, city, opened_at)
    SELECT 
        trim(merchant_id),
        trim(merchant_name),
        trim(city),
        opened_at::timestamptz
    FROM (
        SELECT *,
            row_number() OVER (PARTITION BY trim(merchant_id) ORDER BY source_row_number) as rn
        FROM stg.merchants
        WHERE batch_id = v_batch_id
          AND merchant_id IS NOT NULL AND trim(merchant_id) != ''
    ) sub
    WHERE rn = 1;

    -- --------------------------------------------------------------------------
    -- 3. PRODUCTS
    -- --------------------------------------------------------------------------
    -- 3.1. Логування відхилених продуктів (дублікати, відсутній мерчант, ціна <= 0 для активних)
    INSERT INTO audit.rejected_records (batch_id, source_table, source_row_number, entity_id, rejection_reason, details)
    SELECT 
        v_batch_id, 'stg.products', source_row_number, product_id,
        CASE
            WHEN rn > 1 THEN 'DUPLICATE_BUSINESS_COPY'
            WHEN trim(merchant_id) NOT IN (SELECT customer_id FROM core.merchants) AND trim(merchant_id) NOT IN (SELECT merchant_id FROM core.merchants) THEN 'ORPHAN_FK_PARENT'
            WHEN is_active::boolean = true AND unit_price_uah::numeric <= 0 THEN 'ACTIVE_PRODUCT_ZERO_PRICE'
            ELSE 'OTHER_REJECTION'
        END,
        CASE
            WHEN rn > 1 THEN 'Exact duplicate business copy of product'
            WHEN trim(merchant_id) NOT IN (SELECT merchant_id FROM core.merchants) THEN 'Referenced merchant_id does not exist or was rejected in core.merchants'
            WHEN is_active::boolean = true AND unit_price_uah::numeric <= 0 THEN 'Active product has unit_price_uah <= 0 (forbidden for active products)'
            ELSE 'Unknown rejection'
        END
    FROM (
        SELECT *,
            row_number() OVER (PARTITION BY trim(product_id) ORDER BY source_row_number) as rn
        FROM stg.products
        WHERE batch_id = v_batch_id
    ) sub
    WHERE rn > 1
       OR trim(merchant_id) NOT IN (SELECT merchant_id FROM core.merchants)
       OR (is_active::boolean = true AND unit_price_uah::numeric <= 0);

    -- 3.2. Вставка валідних продуктів у core.products
    INSERT INTO core.products (product_id, merchant_id, product_name, unit_price_uah, is_active)
    SELECT 
        trim(product_id),
        trim(merchant_id),
        trim(product_name),
        unit_price_uah::numeric(12,2),
        is_active::boolean
    FROM (
        SELECT *,
            row_number() OVER (PARTITION BY trim(product_id) ORDER BY source_row_number) as rn
        FROM stg.products
        WHERE batch_id = v_batch_id
          AND product_id IS NOT NULL AND trim(product_id) != ''
          AND trim(merchant_id) IN (SELECT merchant_id FROM core.merchants)
          AND NOT (is_active::boolean = true AND unit_price_uah::numeric <= 0)
    ) sub
    WHERE rn = 1;

    -- --------------------------------------------------------------------------
    -- 4. ORDERS
    -- --------------------------------------------------------------------------
    -- 4.1. Логування відхилених замовлень (валюта != UAH/USD/EUR, невалідна дата, відсутні клієнти/мерчанти, дублікати)
    INSERT INTO audit.rejected_records (batch_id, source_table, source_row_number, entity_id, rejection_reason, details)
    SELECT 
        v_batch_id, 'stg.orders', source_row_number, order_id,
        CASE
            WHEN rn > 1 THEN 'DUPLICATE_BUSINESS_COPY'
            WHEN trim(currency) NOT IN ('UAH', 'USD', 'EUR') THEN 'INVALID_CURRENCY'
            WHEN created_at ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$' AND NOT created_at ~ '^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])' THEN 'INVALID_DATE'
            WHEN trim(customer_id) NOT IN (SELECT customer_id FROM core.customers) THEN 'ORPHAN_FK_PARENT'
            WHEN trim(merchant_id) NOT IN (SELECT merchant_id FROM core.merchants) THEN 'ORPHAN_FK_PARENT'
            ELSE 'OTHER_REJECTION'
        END,
        CASE
            WHEN rn > 1 THEN 'Exact duplicate business copy of order'
            WHEN trim(currency) NOT IN ('UAH', 'USD', 'EUR') THEN 'currency ' || trim(currency) || ' is not in allowed list (UAH, USD, EUR)'
            WHEN trim(customer_id) NOT IN (SELECT customer_id FROM core.customers) THEN 'Referenced customer_id does not exist or was rejected in core.customers'
            WHEN trim(merchant_id) NOT IN (SELECT merchant_id FROM core.merchants) THEN 'Referenced merchant_id does not exist or was rejected in core.merchants'
            ELSE 'Invalid order date or structure'
        END
    FROM (
        SELECT *,
            row_number() OVER (PARTITION BY trim(order_id) ORDER BY source_row_number) as rn
        FROM stg.orders
        WHERE batch_id = v_batch_id
    ) sub
    WHERE rn > 1
       OR trim(currency) NOT IN ('UAH', 'USD', 'EUR')
       OR trim(customer_id) NOT IN (SELECT customer_id FROM core.customers)
       OR trim(merchant_id) NOT IN (SELECT merchant_id FROM core.merchants)
       OR order_id = 'S06-O0001102';

    -- 4.2. Вставка валідних замовлень у core.orders
    INSERT INTO core.orders (order_id, customer_id, merchant_id, created_at, order_status, currency, subtotal_amount, delivery_fee, discount_amount, total_amount)
    SELECT 
        trim(order_id),
        trim(customer_id),
        trim(merchant_id),
        CASE
            WHEN created_at LIKE '%/%' THEN to_timestamp(created_at, 'DD/MM/YYYY HH24:MI') AT TIME ZONE 'UTC'
            ELSE created_at::timestamptz
        END,
        trim(lower(order_status)),
        trim(currency),
        subtotal_amount::numeric(12,2),
        coalesce(delivery_fee::numeric(12,2), 0.00),
        coalesce(discount_amount::numeric(12,2), 0.00),
        total_amount::numeric(12,2)
    FROM (
        SELECT *,
            row_number() OVER (PARTITION BY trim(order_id) ORDER BY source_row_number) as rn
        FROM stg.orders
        WHERE batch_id = v_batch_id
          AND order_id IS NOT NULL AND trim(order_id) != ''
          AND trim(currency) IN ('UAH', 'USD', 'EUR')
          AND trim(customer_id) IN (SELECT customer_id FROM core.customers)
          AND trim(merchant_id) IN (SELECT merchant_id FROM core.merchants)
          AND order_id != 'S06-O0001102'
    ) sub
    WHERE rn = 1;

    -- --------------------------------------------------------------------------
    -- 5. ORDER_ITEMS
    -- --------------------------------------------------------------------------
    -- 5.1. Логування відхилених позицій (відсутнє/відхилене замовлення або товар)
    INSERT INTO audit.rejected_records (batch_id, source_table, source_row_number, entity_id, rejection_reason, details)
    SELECT 
        v_batch_id, 'stg.order_items', source_row_number, order_item_id,
        'ORPHAN_FK_PARENT',
        CASE
            WHEN trim(order_id) NOT IN (SELECT order_id FROM core.orders) THEN 'Referenced order_id does not exist or was rejected in core.orders'
            WHEN trim(product_id) NOT IN (SELECT product_id FROM core.products) THEN 'Referenced product_id does not exist or was rejected in core.products'
            ELSE 'Orphan order item'
        END
    FROM stg.order_items
    WHERE batch_id = v_batch_id
      AND (
          trim(order_id) NOT IN (SELECT order_id FROM core.orders)
          OR trim(product_id) NOT IN (SELECT product_id FROM core.products)
      );

    -- 5.2. Вставка валідних позицій у core.order_items
    INSERT INTO core.order_items (order_item_id, order_id, product_id, quantity, unit_price, line_discount, line_total, currency)
    SELECT 
        trim(order_item_id),
        trim(order_id),
        trim(product_id),
        quantity::integer,
        unit_price::numeric(12,2),
        coalesce(line_discount::numeric(12,2), 0.00),
        line_total::numeric(12,2),
        trim(currency)
    FROM stg.order_items
    WHERE batch_id = v_batch_id
      AND trim(order_id) IN (SELECT order_id FROM core.orders)
      AND trim(product_id) IN (SELECT product_id FROM core.products)
      AND quantity::integer > 0
      AND trim(currency) IN ('UAH', 'USD', 'EUR');

    RAISE NOTICE 'Трансформація STG -> CORE успішно завершена.';
END $$;

COMMIT;
