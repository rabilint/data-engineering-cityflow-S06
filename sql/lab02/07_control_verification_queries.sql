-- ==============================================================================
-- Лабораторна робота 2: Чотири контрольні SQL-перевірки (Завдання 9)
-- ==============================================================================
-- Цей файл містить 4 обов'язкові контрольні аналітичні запити:
-- 1. Перевірка відсутності дублікатів PK у всіх таблицях ядра (очікується 0).
-- 2. Контроль відсутності розірваних/висячих FK (очікується 0).
-- 3. Звірка рядків та сум за валютами між accepted-вибіркою staging та core.
-- 4. Демонстрація проблеми завищення сум при JOIN (fan-out multiplication)
--    та правильні запити на належному рівні деталізації (grain).
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- ПЕРЕВІРКА 1: Дублікати первинних ключів (PK) у кожній core-таблиці
-- Очікуваний результат: 0 рядків для кожної таблиці ядра.
-- ------------------------------------------------------------------------------

SELECT 'core.customers' AS table_name, count(*) - count(DISTINCT customer_id) AS duplicate_pk_count FROM core.customers
UNION ALL
SELECT 'core.merchants', count(*) - count(DISTINCT merchant_id) FROM core.merchants
UNION ALL
SELECT 'core.products', count(*) - count(DISTINCT product_id) FROM core.products
UNION ALL
SELECT 'core.orders', count(*) - count(DISTINCT order_id) FROM core.orders
UNION ALL
SELECT 'core.order_items', count(*) - count(DISTINCT order_item_id) FROM core.order_items;


-- ------------------------------------------------------------------------------
-- ПЕРЕВІРКА 2: Контроль цілісності зовнішніх ключів (FK Integrity)
-- Очікуваний результат: 0 сирітських (orphan) записів для всіх зв'язків.
-- ------------------------------------------------------------------------------

SELECT 
    'products -> merchants' AS relationship,
    count(*) AS orphan_foreign_keys
FROM core.products p
LEFT JOIN core.merchants m ON p.merchant_id = m.merchant_id
WHERE m.merchant_id IS NULL

UNION ALL

SELECT 
    'orders -> customers',
    count(*)
FROM core.orders o
LEFT JOIN core.customers c ON o.customer_id = c.customer_id
WHERE c.customer_id IS NULL

UNION ALL

SELECT 
    'orders -> merchants',
    count(*)
FROM core.orders o
LEFT JOIN core.merchants m ON o.merchant_id = m.merchant_id
WHERE m.merchant_id IS NULL

UNION ALL

SELECT 
    'order_items -> orders',
    count(*)
FROM core.order_items oi
LEFT JOIN core.orders o ON oi.order_id = o.order_id
WHERE o.order_id IS NULL

UNION ALL

SELECT 
    'order_items -> products',
    count(*)
FROM core.order_items oi
LEFT JOIN core.products p ON oi.product_id = p.product_id
WHERE p.product_id IS NULL;


-- ------------------------------------------------------------------------------
-- ПЕРЕВІРКА 3: Рядки й суми за currency до/після публікації (staging accepted vs core)
-- Очікуваний результат: абсолютна різниця diff = 0.00 для всіх валют.
-- ------------------------------------------------------------------------------

WITH stg_accepted_orders AS (
    SELECT 
        payload->>'currency' AS currency,
        count(*) AS stg_orders_count,
        SUM((payload->>'total_amount')::NUMERIC(12,2)) AS stg_orders_sum
    FROM audit.record_decisions
    WHERE source_file = 'orders.csv' 
      AND final_status = 'accepted'
      AND batch_id = (SELECT batch_id FROM audit.load_batches WHERE status = 'SUCCESS' ORDER BY completed_at DESC LIMIT 1)
    GROUP BY payload->>'currency'
),
core_orders_summary AS (
    SELECT 
        currency,
        count(*) AS core_orders_count,
        SUM(total_amount) AS core_orders_sum
    FROM core.orders
    GROUP BY currency
),
stg_accepted_items AS (
    SELECT 
        payload->>'currency' AS currency,
        count(*) AS stg_items_count,
        SUM((payload->>'line_total')::NUMERIC(12,2)) AS stg_items_sum
    FROM audit.record_decisions
    WHERE source_file = 'order_items.csv' 
      AND final_status = 'accepted'
      AND batch_id = (SELECT batch_id FROM audit.load_batches WHERE status = 'SUCCESS' ORDER BY completed_at DESC LIMIT 1)
    GROUP BY payload->>'currency'
),
core_items_summary AS (
    SELECT 
        currency,
        count(*) AS core_items_count,
        SUM(line_total) AS core_items_sum
    FROM core.order_items
    GROUP BY currency
)
SELECT 
    co.currency,
    so.stg_orders_count,
    co.core_orders_count,
    abs(co.core_orders_count - so.stg_orders_count) AS orders_count_diff,
    so.stg_orders_sum,
    co.core_orders_sum,
    abs(co.core_orders_sum - so.stg_orders_sum) AS orders_amount_diff,
    si.stg_items_count,
    ci.core_items_count,
    abs(ci.core_items_count - si.stg_items_count) AS items_count_diff,
    si.stg_items_sum,
    ci.core_items_sum,
    abs(ci.core_items_sum - si.stg_items_sum) AS items_amount_diff
FROM core_orders_summary co
JOIN stg_accepted_orders so ON co.currency = so.currency
JOIN core_items_summary ci ON co.currency = ci.currency
JOIN stg_accepted_items si ON co.currency = si.currency
ORDER BY co.currency;


-- ------------------------------------------------------------------------------
-- ПЕРЕВІРКА 4: Проблема завищення сум (Fan-out Multiplication) при JOIN з order_items
-- ------------------------------------------------------------------------------

-- А. НЕПРАВИЛЬНИЙ (наївний) запит:
-- При об'єднанні orders 1 : N order_items кожен рядок замовлення дублюється
-- стільки разів, скільки товарних позицій є в замовленні.
-- У результаті сума total_amount для UAH завищується майже втричі (10 090 175.31 замість 3 593 078.92)!
SELECT 
    o.currency,
    SUM(o.total_amount) AS inflated_orders_total_amount,
    count(*) AS joined_rows_count
FROM core.orders o
JOIN core.order_items oi ON o.order_id = oi.order_id
GROUP BY o.currency
ORDER BY o.currency;


-- Б. ЧОМУ ЗАБОРОНЕНО ВИПРАВЛЯТИ ЧЕРЕЗ SUM(DISTINCT o.total_amount):
-- Якщо застосувати SUM(DISTINCT total_amount), PostgreSQL згорне всі різні замовлення,
-- які випадково мають однакову фінансову суму (наприклад, чек на 150.00 грн чи 200.00 грн),
-- в ОДНЕ значення!
-- У результаті замість реального виторгу 3 593 078.92 грн запит поверне 3 517 524.07 грн,
-- тобто штучно "знищить" понад 75 554 грн законного виторгу!
SELECT 
    currency,
    SUM(DISTINCT total_amount) AS flawed_collapsed_total_amount,
    (SELECT SUM(total_amount) FROM core.orders o2 WHERE o2.currency = o1.currency) AS real_total_amount,
    (SELECT SUM(total_amount) FROM core.orders o2 WHERE o2.currency = o1.currency) - SUM(DISTINCT total_amount) AS illegally_lost_revenue
FROM core.orders o1
GROUP BY currency
ORDER BY currency;


-- В. ПРАВИЛЬНИЙ ЗАПИТ 1 (Рівень деталізації / Grain = Замовлення):
-- Оскільки total_amount є атрибутом сутності Замовлення (Order-level fact),
-- його агрегація повинна виконуватися безпосередньо по таблиці замовлень:
SELECT 
    currency,
    count(*) AS orders_count,
    SUM(total_amount) AS correct_orders_total_amount
FROM core.orders
GROUP BY currency
ORDER BY currency;


-- Г. ПРАВИЛЬНИЙ ЗАПИТ 2 (Рівень деталізації з перед-агрегацією дочірніх рядків):
-- Якщо в аналітичному звіті необхідно одночасно показати total_amount замовлення
-- та агреговані метрики позицій (наприклад, кількість куплених штук чи суму позицій),
-- дочірню таблицю order_items обов'язково згортають (GROUP BY order_id) ДО операції JOIN:
WITH order_items_aggregated AS (
    SELECT 
        order_id,
        SUM(quantity) AS total_items_quantity,
        SUM(line_total) AS total_items_revenue
    FROM core.order_items
    GROUP BY order_id
)
SELECT 
    o.currency,
    count(o.order_id) AS orders_count,
    SUM(o.total_amount) AS correct_orders_total_amount,
    SUM(oi.total_items_quantity) AS correct_total_quantity_sold,
    SUM(oi.total_items_revenue) AS correct_net_items_revenue
FROM core.orders o
LEFT JOIN order_items_aggregated oi ON o.order_id = oi.order_id
GROUP BY o.currency
ORDER BY o.currency;
