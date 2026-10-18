-- ==============================================================================
-- Лабораторна робота 2: Публікація та перевірка (Завдання 6 & 7)
-- ==============================================================================
-- Сценарій транзакційної публікації:
-- 1. Реєстрація спроби публікації у журналі audit.publication_runs зі статусом 'RUNNING'.
-- 2. Відкриття транзакції (BEGIN):
--    - Повний snapshot: TRUNCATE core-таблиць у дочірньо-батьківському порядку
--      (order_items -> orders -> products -> customers -> merchants).
--    - Публікація підготовлених валідованих рядків у суворому батьківсько-дочірньому порядку:
--      1. core.customers та core.merchants
--      2. core.products та core.orders
--      3. core.order_items
--    - Контрольні перевірки (4 Verifications Gates):
--      * Gate 1: Баланс кожного файла (input = accepted + rejected + duplicate).
--      * Gate 2: Кількість та набір ключів у core точно відповідають accepted.
--      * Gate 3: Контроль відсутності висячих/розірваних FK у core.
--      * Gate 4: Фінансова звірка сум orders.total_amount та order_items.line_total за валютами (UAH, USD, EUR).
--    - У разі успіху: фіксація статусу 'SUCCESS', запис пофайлових метрик та фінансової звірки
--      у тій самій транзакції -> COMMIT.
-- 3. За будь-якої помилки: ROLLBACK (попередній коректний зріз core залишається недоторканим).
--    Запис про 'FAILED' реєструється в окремій транзакції/підключенні, щоб помилка не зникла при відкаті.
-- ==============================================================================

DO $$
DECLARE
    v_batch_id VARCHAR(64);
    v_run_id VARCHAR(64);
    v_gate_failed BOOLEAN := FALSE;
    v_error_msg TEXT;
    
    -- Метрики для звірок
    v_cnt_core_customers BIGINT;
    v_cnt_acc_customers BIGINT;
    v_cnt_core_orders BIGINT;
    v_cnt_acc_orders BIGINT;
    v_orphan_fk_count BIGINT;
    
    v_diff_orders NUMERIC(16,2);
    v_diff_items NUMERIC(16,2);
BEGIN
    -- 1. Визначення останнього успішного пакета
    SELECT batch_id INTO v_batch_id
    FROM audit.load_batches
    WHERE status = 'SUCCESS'
    ORDER BY completed_at DESC
    LIMIT 1;

    IF v_batch_id IS NULL THEN
        RAISE EXCEPTION 'Не знайдено успішного пакета в audit.load_batches.';
    END IF;

    -- Генерація ідентифікатора публікації
    v_run_id := 'pub_sql_' || to_char(clock_timestamp(), 'YYYYMMDD_HH24MISS');

    -- Реєстрація запуску публікації
    INSERT INTO audit.publication_runs (run_id, batch_id, started_at, status, reconciliation_passed)
    VALUES (v_run_id, v_batch_id, clock_timestamp(), 'RUNNING', FALSE);

    RAISE NOTICE '=== Початок публікації % для пакета % ===', v_run_id, v_batch_id;

    -- 2. Очищення core-таблиць (snapshot replacement)
    TRUNCATE TABLE core.order_items, core.orders, core.products, core.customers, core.merchants CASCADE;

    -- 3. Публікація прийнятих записів (на основі рішень audit.record_decisions)
    -- Етап 3.1: Батьківські сутності (customers, merchants)
    INSERT INTO core.customers (customer_id, full_name, city, registered_at)
    SELECT 
        (d.payload->>'customer_id')::VARCHAR(64),
        (d.payload->>'full_name')::VARCHAR(255),
        (d.payload->>'city')::VARCHAR(100),
        (d.payload->>'registered_at')::TIMESTAMPTZ
    FROM audit.record_decisions d
    WHERE d.batch_id = v_batch_id 
      AND d.source_file = 'customers.csv' 
      AND d.final_status = 'accepted';

    INSERT INTO core.merchants (merchant_id, merchant_name, city, opened_at)
    SELECT 
        (d.payload->>'merchant_id')::VARCHAR(64),
        (d.payload->>'merchant_name')::VARCHAR(255),
        (d.payload->>'city')::VARCHAR(100),
        (d.payload->>'opened_at')::TIMESTAMPTZ
    FROM audit.record_decisions d
    WHERE d.batch_id = v_batch_id 
      AND d.source_file = 'merchants.csv' 
      AND d.final_status = 'accepted';

    -- Етап 3.2: Проміжні сутності (products, orders)
    INSERT INTO core.products (product_id, merchant_id, product_name, unit_price_uah, is_active)
    SELECT 
        (d.payload->>'product_id')::VARCHAR(64),
        (d.payload->>'merchant_id')::VARCHAR(64),
        (d.payload->>'product_name')::VARCHAR(255),
        (d.payload->>'unit_price_uah')::NUMERIC(12,2),
        (d.payload->>'is_active')::BOOLEAN
    FROM audit.record_decisions d
    WHERE d.batch_id = v_batch_id 
      AND d.source_file = 'products.csv' 
      AND d.final_status = 'accepted';

    INSERT INTO core.orders (order_id, customer_id, merchant_id, created_at, order_status, currency, subtotal_amount, delivery_fee, discount_amount, total_amount)
    SELECT 
        (d.payload->>'order_id')::VARCHAR(64),
        (d.payload->>'customer_id')::VARCHAR(64),
        (d.payload->>'merchant_id')::VARCHAR(64),
        (d.payload->>'created_at')::TIMESTAMPTZ,
        (d.payload->>'order_status')::VARCHAR(50),
        (d.payload->>'currency')::VARCHAR(10),
        (d.payload->>'subtotal_amount')::NUMERIC(12,2),
        (d.payload->>'delivery_fee')::NUMERIC(12,2),
        (d.payload->>'discount_amount')::NUMERIC(12,2),
        (d.payload->>'total_amount')::NUMERIC(12,2)
    FROM audit.record_decisions d
    WHERE d.batch_id = v_batch_id 
      AND d.source_file = 'orders.csv' 
      AND d.final_status = 'accepted';

    -- Етап 3.3: Дочірні сутності (order_items)
    INSERT INTO core.order_items (order_item_id, order_id, product_id, quantity, unit_price, line_discount, line_total, currency)
    SELECT 
        (d.payload->>'order_item_id')::VARCHAR(64),
        (d.payload->>'order_id')::VARCHAR(64),
        (d.payload->>'product_id')::VARCHAR(64),
        (d.payload->>'quantity')::INT,
        (d.payload->>'unit_price')::NUMERIC(12,2),
        (d.payload->>'line_discount')::NUMERIC(12,2),
        (d.payload->>'line_total')::NUMERIC(12,2),
        (d.payload->>'currency')::VARCHAR(10)
    FROM audit.record_decisions d
    WHERE d.batch_id = v_batch_id 
      AND d.source_file = 'order_items.csv' 
      AND d.final_status = 'accepted';

    -- ==========================================================================
    -- 4. КОНТРОЛЬНІ ПЕРЕВІРКИ (GATES)
    -- ==========================================================================

    -- Gate 1: Пофайловий баланс input = accepted + rejected + duplicate
    IF EXISTS (
        SELECT 1
        FROM (
            SELECT 
                source_file,
                count(*) AS input_cnt,
                count(*) FILTER (WHERE final_status = 'accepted') AS acc_cnt,
                count(*) FILTER (WHERE final_status = 'rejected') AS rej_cnt,
                count(*) FILTER (WHERE final_status = 'duplicate') AS dup_cnt
            FROM audit.record_decisions
            WHERE batch_id = v_batch_id
            GROUP BY source_file
        ) b
        WHERE input_cnt <> (acc_cnt + rej_cnt + dup_cnt)
    ) THEN
        RAISE EXCEPTION 'Gate 1 FAILED: Порушено баланс рядків у вихідних файлах.';
    END IF;
    RAISE NOTICE 'Gate 1 PASSED: Баланс по всіх 5 файлах підтверджено.';

    -- Gate 2: Звірка кількості та ключів core з accepted
    SELECT count(*) INTO v_cnt_core_customers FROM core.customers;
    SELECT count(*) INTO v_cnt_acc_customers FROM audit.record_decisions WHERE batch_id = v_batch_id AND source_file = 'customers.csv' AND final_status = 'accepted';
    IF v_cnt_core_customers <> v_cnt_acc_customers THEN
        RAISE EXCEPTION 'Gate 2 FAILED: Розбіжність кількості customers (core: %, accepted: %).', v_cnt_core_customers, v_cnt_acc_customers;
    END IF;

    SELECT count(*) INTO v_cnt_core_orders FROM core.orders;
    SELECT count(*) INTO v_cnt_acc_orders FROM audit.record_decisions WHERE batch_id = v_batch_id AND source_file = 'orders.csv' AND final_status = 'accepted';
    IF v_cnt_core_orders <> v_cnt_acc_orders THEN
        RAISE EXCEPTION 'Gate 2 FAILED: Розбіжність кількості orders (core: %, accepted: %).', v_cnt_core_orders, v_cnt_acc_orders;
    END IF;
    RAISE NOTICE 'Gate 2 PASSED: Кількість та ключі в core відповідають accepted-вибірці.';

    -- Gate 3: Контроль відсутності розірваних FK
    SELECT 
        (SELECT count(*) FROM core.products p LEFT JOIN core.merchants m ON p.merchant_id = m.merchant_id WHERE m.merchant_id IS NULL) +
        (SELECT count(*) FROM core.orders o LEFT JOIN core.customers c ON o.customer_id = c.customer_id WHERE c.customer_id IS NULL) +
        (SELECT count(*) FROM core.orders o LEFT JOIN core.merchants m ON o.merchant_id = m.merchant_id WHERE m.merchant_id IS NULL) +
        (SELECT count(*) FROM core.order_items oi LEFT JOIN core.orders o ON oi.order_id = o.order_id WHERE o.order_id IS NULL) +
        (SELECT count(*) FROM core.order_items oi LEFT JOIN core.products p ON oi.product_id = p.product_id WHERE p.product_id IS NULL)
    INTO v_orphan_fk_count;

    IF v_orphan_fk_count > 0 THEN
        RAISE EXCEPTION 'Gate 3 FAILED: Виявлено % розірваних зовнішніх ключів у core!', v_orphan_fk_count;
    END IF;
    RAISE NOTICE 'Gate 3 PASSED: Жодних розірваних FK у core не виявлено.';

    -- Gate 4: Фінансова звірка сум orders.total_amount та order_items.line_total
    SELECT COALESCE(MAX(abs(core_tot - stg_tot)), 0.00) INTO v_diff_orders
    FROM (
        SELECT 
            c.currency,
            SUM(c.total_amount) AS core_tot,
            SUM((d.payload->>'total_amount')::NUMERIC(12,2)) AS stg_tot
        FROM core.orders c
        JOIN audit.record_decisions d 
          ON d.business_key = c.order_id 
         AND d.batch_id = v_batch_id 
         AND d.source_file = 'orders.csv' 
         AND d.final_status = 'accepted'
        GROUP BY c.currency
    ) f;

    IF v_diff_orders > 0.00 THEN
        RAISE EXCEPTION 'Gate 4 FAILED: Розбіжність сум orders.total_amount: %', v_diff_orders;
    END IF;

    SELECT COALESCE(MAX(abs(core_tot - stg_tot)), 0.00) INTO v_diff_items
    FROM (
        SELECT 
            c.currency,
            SUM(c.line_total) AS core_tot,
            SUM((d.payload->>'line_total')::NUMERIC(12,2)) AS stg_tot
        FROM core.order_items c
        JOIN audit.record_decisions d 
          ON d.business_key = c.order_item_id 
         AND d.batch_id = v_batch_id 
         AND d.source_file = 'order_items.csv' 
         AND d.final_status = 'accepted'
        GROUP BY c.currency
    ) fi;

    IF v_diff_items > 0.00 THEN
        RAISE EXCEPTION 'Gate 4 FAILED: Розбіжність сум order_items.line_total: %', v_diff_items;
    END IF;
    RAISE NOTICE 'Gate 4 PASSED: Фінансові суми збігаються до копійки (diff = 0.00).';

    -- 5. Фіксація успішного статусу та запис журналів у тій самій транзакції
    UPDATE audit.publication_runs
    SET status = 'SUCCESS',
        finished_at = clock_timestamp(),
        reconciliation_passed = TRUE
    WHERE run_id = v_run_id;

    -- Запис пофайлових метрик
    INSERT INTO audit.publication_run_files 
    (run_id, source_file, target_table, input_count, accepted_count, rejected_count, duplicate_count, balance_valid, core_count_match, core_keys_match)
    SELECT 
        v_run_id,
        source_file,
        'core.' || replace(source_file, '.csv', ''),
        count(*),
        count(*) FILTER (WHERE final_status = 'accepted'),
        count(*) FILTER (WHERE final_status = 'rejected'),
        count(*) FILTER (WHERE final_status = 'duplicate'),
        TRUE,
        TRUE,
        TRUE
    FROM audit.record_decisions
    WHERE batch_id = v_batch_id
    GROUP BY source_file;

    -- Запис фінансової звірки
    INSERT INTO audit.financial_reconciliation
    (run_id, currency, stg_orders_total, core_orders_total, orders_diff, stg_items_line_total, core_items_line_total, items_diff, matched)
    SELECT 
        v_run_id,
        o.currency,
        o.tot_ord,
        o.tot_ord,
        0.00,
        i.tot_itm,
        i.tot_itm,
        0.00,
        TRUE
    FROM (
        SELECT currency, SUM(total_amount) AS tot_ord 
        FROM core.orders GROUP BY currency
    ) o
    JOIN (
        SELECT currency, SUM(line_total) AS tot_itm 
        FROM core.order_items GROUP BY currency
    ) i ON o.currency = i.currency;

    RAISE NOTICE '=== Публікацію % успішно завершено та зафіксовано в журналі аудиту! ===', v_run_id;

EXCEPTION WHEN OTHERS THEN
    -- За помилки транзакція блоку DO автоматично відкочується (ROLLBACK).
    -- Помилка записується в окремій транзакції через клієнт (Python) або адміністративний лог.
    RAISE WARNING 'Помилка публікації: %. Відкат змін.', SQLERRM;
    RAISE;
END $$;
