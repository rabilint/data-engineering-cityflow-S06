# Журнал змін (Change Log) проекту

У цьому документі фіксуються всі зміни коду, схем даних, тестів та документації з прив'язкою до файлів, діапазонів рядків та конкретних завдань лабораторної роботи.

---

## [Завдання 8] Перевірка повторного запуску та контрольованого збою (Reliability & Rollback)

* **Мета:**
  1. Перевірити ідемпотентність повторного запуску на тому самому пакеті: двічі виконати публікацію core, перевірити незмінність кількості рядків у всіх 5 core-таблицях, повну відповідність набору первинних ключів та ідентичність фінансових сум за валютами (UAH, USD, EUR). Забезпечити реєстрацію нового незалежного запису зі статусом SUCCESS у журналі audit.publication_runs.
  2. Заборонити мовчазний перезапис історії при зміні даних під тим самим batch_id за допомогою винятку BatchContentChangedError.
  3. На окремому синтетичному наборі спричинити контрольовану помилку після початку модифікації core (ін'єкція дочірнього рядка з quantity = -1, що порушує обмеження CHECK (quantity > 0)).
  4. Довести, що механізм ROLLBACK повернув попередній коректний стан усіх 5 змінених таблиць ядра, а запис про невдалу спробу (status = 'FAILED') разом із точним текстом помилки зберігся у audit.publication_runs (через автономне підключення після відкату).
  5. Продемонструвати успішний повторний запуск виправленого процесу (status = 'SUCCESS').
  6. Реалізувати негативні тести зупинки процесу до початку публікації (fail-fast) при пошкодженому заголовку або відсутності обов'язкового файлу. Навмисні test fixtures зберігати ізольовано від data/raw/.
* **Дата:** 18.10.2026

### Змінені та створені файли:

1. [src/lab02/publish_core.py](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/src/lab02/publish_core.py)
   * **Діапазон рядків:** L58–L65 та L280–L435
   * **Зміни:**
     * Додано клас винятку BatchContentChangedError.
     * Додано верифікацію цілісності пакета: порівняння кількості вхідних рядків поточного запуску з попереднім успішним публікаційним запуском для того самого batch_id для виявлення та блокування тихого перезапису.
     * Реалізовано параметр inject_invalid_item для контрольованого тестування збою: ін'єкція рядка в core.order_items із quantity = -1 після очищення та вставки батьківських сутностей.
     * Забезпечено виклик ROLLBACK та автономний запис статусу FAILED у audit.publication_runs.
2. [tests/fixtures/corrupted_files/corrupted_customers.csv](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/tests/fixtures/corrupted_files/corrupted_customers.csv)
   * **Діапазон рядків:** L1–L3 (новий файл)
   * **Зміни:** Ізольований синтетичний тестовий CSV-файл із пошкодженим заголовком (пропущені обов'язкові колонки, зокрема city, phone, service_zone_id), збережений окремо від робочих даних data/raw/.
3. [tests/test_reliability_and_failures.py](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/tests/test_reliability_and_failures.py)
   * **Діапазон рядків:** L1–L170 (новий файл)
   * **Зміни:** Набір із 4-х автоматизованих інтеграційних тестів:
     * test_rerun_idempotency_same_batch: двічі публікує один і той самий пакет, порівнює count(*), множини PK через array_agg та суми замовлень/позицій за кожною валютою; перевіряє фіксацію 2 успішних записів у журналі.
     * test_controlled_failure_check_constraint_rollback: викликає публікацію з inject_invalid_item=True, ловить виняток порушення CHECK constraint, перевіряє незмінність кількості записів у core.customers, core.orders, core.order_items після збою, перевіряє фіксацію FAILED у журналі та виконує успішний повторний запуск виправленого процесу.
     * test_negative_corrupted_header_pre_publication_stop: перевіряє виклик StructuralValidationError та зупинку до публікації при невалідному заголовку.
     * test_negative_missing_mandatory_file_pre_publication_stop: перевіряє переривання процесу при відсутності обов'язкового файлу.

---

## [Завдання 9] Чотири контрольні SQL-перевірки та аналіз рівня деталізації (Grain Analysis)

* **Мета:**
  1. Створити окремий SQL-скрипт із 4-ма обов'язковими аналітичними контрольними перевірками.
  2. Перевірка 1: Перевірити відсутність дублікатів PK у кожній із 5 таблиць ядра (очікується 0).
  3. Перевірка 2: Перевірити відсутність розірваних/сирітських зовнішніх ключів (orphan FK) за всіма зв'язками між таблицями core (очікується 0).
  4. Перевірка 3: Порівняти кількість рядків та фінансові суми замовлень (total_amount) і позицій (line_total) між прийнятою staging-вибіркою (audit.record_decisions) та core-таблицями окремо для кожної валюти (UAH, USD, EUR). Очікується абсолютний збіг (diff = 0.00).
  5. Перевірка 4: Продемонструвати явище завищення SUM(orders.total_amount) при наївному JOIN core.order_items (проблема кардинальності 1:N / fan-out multiplication). Довести неприпустимість виправлення через SUM(DISTINCT total_amount) через втрату законного виторгу від однакових чеків. Надати правильні запити з поясненням рівня деталізації (grain).
  6. Створити допоміжну утиліту для зручного запуску SQL-файлів із виведенням форматованих таблиць безпосередньо в консоль.
* **Дата:** 18.10.2026

### Змінені та створені файли:

1. [sql/lab02/07_control_verification_queries.sql](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/sql/lab02/07_control_verification_queries.sql)
   * **Діапазон рядків:** L1–L185 (новий файл)
   * **Зміни:** 
     * Запит 1: Перевірка count(*) - count(DISTINCT pk) для customers, merchants, products, orders, order_items (всі значення = 0).
     * Запит 2: Перевірка LEFT JOIN ... WHERE parent.pk IS NULL для 5 зв'язків (всі значення = 0).
     * Запит 3: CTE-запит порівняння сум і кількості рядків accepted staging проти core за валютами UAH, USD, EUR (всі diff = 0.00).
     * Запит 4: Наочна демонстрація наївного JOIN: сума чеків замовлень у гривні зростає з 3 593 078.92 грн до 10 090 175.31 грн через повторення замовлення для кожного товару.
     * Запит 5: Доказ деструктивності SUM(DISTINCT total_amount): сума чеків схлопується до 3 517 524.07 грн, втрачаючи 75 554.85 грн виторгу.
     * Запити 6 & 7: Архітектурно правильні рішення на рівні зернистості замовлення (Grain = Order) та з перед-агрегацією дочірніх рядків перед JOIN.
2. [src/lab02/run_sql.py](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/src/lab02/run_sql.py)
   * **Діапазон рядків:** L1–L75 (новий файл)
   * **Зміни:** Консольна Python-утиліта для виконання довільних SQL-скриптів на базі DB_CONFIG з автоматичним розрахунком ширини стовпців та виведенням результатів у вигляді ASCII-таблиць.

---

## [Завдання 10] Оформлення відтворюваного результату (Reproducibility & Presentation)

* **Мета:**
  1. Оформити вичерпний головний документ репозиторію README.md із описом архітектури шарів даних (Staging, Audit, Core).
  2. Зафіксувати версії програмного забезпечення (PostgreSQL 16+, Python 3.14.2) та параметри конфігурації без секретів через шаблон .env.example.
  3. Описати покроковий порядок відтворення всього процесу з нуля: виконання DDL, завантаження сирих даних у staging, фільтрація за правилами приймання, транзакційна публікація core, виконання SQL-перевірок та запуск автоматичних тестів.
  4. Скласти детальну таблицю Source-to-Target Mapping із описом правил приведення типів, трансформацій та збереження первинного контексту для всіх полів.
  5. Розробити Mermaid ER-діаграму сутностей ядра, їх атрибутів, первинних/зовнішніх ключів та зв'язків.
  6. Описати політику повного snapshot (заміна реляційного ядра в одній транзакції) та зафіксувати відомі якісні особливості джерела (незалежні заокруглення +- 0.01 у 20 замовленнях, аномальне замовлення S06-O0000773, історичні ціни чека проти поточної вітрини UAH).
  7. Зафіксувати актуальні бібліотеки Python у requirements.txt (psycopg2-binary>=2.9.9, pytest>=8.0.0) та перевірити чистоту Git-дерева через .gitignore (без великих CSV та бінарних дампів).
* **Дата:** 18.10.2026

### Змінені та створені файли:

1. [README.md](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/README.md)
   * **Діапазон рядків:** L1–L250 (повна переробка файлу)
   * **Зміни:**
     * Розділ 1: Mermaid-діаграма архітектури потоків даних між шарами Sources -> Staging -> Audit -> Core.
     * Розділ 2: Системні вимоги (PostgreSQL 16+, Python 3.14.2).
     * Розділ 3: Налаштування .env та віртуального оточення.
     * Розділ 4: Відтворюваний покроковий сценарій запуску команд Крок 1 – Крок 6.
     * Розділ 5: Mermaid ER-діаграма ядра core.* із PK, FK та типами даних.
     * Розділ 6: Таблиця Source-to-Target Mapping для всіх 30+ атрибутів.
     * Розділ 7: Звіт про проходження 4-х контрольних SQL-перевірок та аналіз Grain.
     * Розділ 8: Діагностика первинних даних та відомі обмеження.
2. [requirements.txt](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/requirements.txt)
   * **Діапазон рядків:** L98–L102
   * **Зміни:** Додано залежності psycopg2-binary>=2.9.9 та pytest>=8.0.0.
3. [.gitignore](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/.gitignore)
   * **Діапазон рядків:** L15–L20
   * **Зміни:** Налаштовано виключення для розпакованих каталогів сирих даних (*дані*), щоб запобігти випадковому потраплянню гігабайтних CSV та дампу до Git-історії.

---

## [Завдання 6 & 7] Транзакційна публікація core, журнал запусків та 4-рівнева звірка якості

* **Мета:** 
  1. Створити реляційне ядро core.* з повними обмеженнями PRIMARY KEY, FOREIGN KEY, NOT NULL та узгодженими CHECK (quantity > 0, невід'ємні суми NUMERIC(12,2), допустимі валюти UAH, USD, EUR).
  2. Реалізувати атомарну публікацію повного зрізу (snapshot replacement) в межах однієї ACID-транзакції у суворому ієрархічному порядку (customers/merchants -> products/orders -> order_items).
  3. Забезпечити збереження попереднього стану при помилці (ROLLBACK) без видалення stg, audit або сирих CSV.
  4. Створити журнал спроб публікації audit.publication_runs зі статусами RUNNING (до публікації), SUCCESS (разом з публікацією), FAILED (в окремій транзакції після відкату).
  5. Реалізувати 4 автоматизовані контрольні перевірки (Verification Gates):
     * Gate 1: Пофайловий баланс input = accepted + rejected + duplicate.
     * Gate 2: Повна звірка кількості та набору первинних ключів у core з множиною accepted.
     * Gate 3: Контроль відсутності висячих/розірваних зовнішніх ключів у core.
     * Gate 4: Фінансова звірка сум orders.total_amount та order_items.line_total за валютами (UAH, USD, EUR) із точністю до копійки (0.00).
  6. Провести поглиблений фінансовий аналіз та діагностику розбіжностей у джерелі (незалежні заокруглення +- 0.01 у 20 замовленнях, аномальне замовлення S06-O0000773, пояснення зв'язку брутто subtotal_amount та нетто line_total, неможливість заміни історичних цін чека на поточні ціни вітрини в UAH).
* **Дата:** 18.10.2026

### Змінені та створені файли:

1. [sql/lab02/01_create_schemas.sql](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/sql/lab02/01_create_schemas.sql)
   * **Діапазон рядків:** L75–L125
   * **Зміни:** Додано DDL-структури для журналу спроб публікації audit.publication_runs, пофайлових метрик з перевіркою балансу audit.publication_run_files та фінансової звірки сум audit.financial_reconciliation.
2. [sql/lab02/03_create_core_tables.sql](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/sql/lab02/03_create_core_tables.sql)
   * **Діапазон рядків:** L35–L68
   * **Зміни:** Узгоджено суворі обмеження цілісності: quantity INT NOT NULL CHECK (quantity > 0), CHECK (currency IN ('UAH', 'USD', 'EUR')), CHECK (unit_price_uah >= 0), CHECK (total_amount >= 0) тощо.
3. [src/lab02/publish_core.py](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/src/lab02/publish_core.py)
   * **Діапазон рядків:** L1–L395 (новий файл)
   * **Зміни:**
     * Функція publish_core: повний транзакційний цикл заміни зрізу core.
     * Попередня реєстрація RUNNING в окремій транзакції.
     * Реалізація функцій верифікації: verify_gate_1_file_balance, verify_gate_2_core_counts_and_keys, verify_gate_3_fk_integrity, verify_gate_4_financial_reconciliation.
     * Фіксація SUCCESS у тій самій транзакції або ROLLBACK + запис FAILED в окремому з'єднанні.
     * CLI інтерфейс з параметром --simulate-error для перевірки відкатів.
4. [sql/lab02/06_publish_and_reconcile.sql](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/sql/lab02/06_publish_and_reconcile.sql)
   * **Діапазон рядків:** L1–L230 (новий файл)
   * **Зміни:** Чистий PL/pgSQL анонімний блок для публікації core з виконанням усіх 4 контрольних перевірок безпосередньо в СУБД.
5. [tests/test_publication_reconciliation.py](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/tests/test_publication_reconciliation.py)
   * **Діапазон рядків:** L1–L135 (новий файл)
   * **Зміни:** 6 інтеграційних тестів: успішна публікація, збереження даних після rollback, перевірка Gate 1, Gate 2, Gate 3 та Gate 4.
6. [docs/lab02/reconciliation_and_financial_diagnostics.md](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/docs/lab02/reconciliation_and_financial_diagnostics.md)
   * **Діапазон рядків:** L1–L140 (новий файл)
   * **Зміни:** Детальний технічний звіт з фінансовою діагностикою, порівняльними таблицями сум, аналізом аномалій джерела та інструкціями з запуску.

---

## [Завдання 5] Збереження рішення для кожного входу (Record Decisions)

* **Мета:** Створити підсумковий статус (accepted, rejected, duplicate) для кожного рядка CSV із збереженням batch_id, source_file, source_row_number, business_key, reason_codes (список причин) та сирого payload без видалення рядків зі staging. Створити окремий ізольований fixture для тестування.
* **Дата:** 18.10.2026

### Змінені та створені файли:

1. [sql/lab02/01_create_schemas.sql](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/sql/lab02/01_create_schemas.sql)
   * **Діапазон рядків:** L51–L74
   * **Зміни:** Додано DDL таблиці audit.record_decisions (decision_id, batch_id, source_file, source_row_number, business_key, final_status, reason_codes TEXT[], details, payload JSONB, created_at) та індекси для швидкої аналітики.
2. [src/lab02/load_core.py](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/src/lab02/load_core.py)
   * **Діапазон рядків:** L112–L550 та L552–L630
   * **Зміни:**
     * Для кожного запису генерується запис рішення з рівно одним final_status (accepted, rejected, duplicate).
     * Реалізовано збереження кількох причин відхилення в одному списку reason_codes.
     * Додано пакетне збереження всіх 21 210 рішень у таблицю audit.record_decisions.
     * Забезпечено збереження сирого JSON-пейлоаду (payload) кожного рядка.
3. [tests/test_record_decisions.py](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/tests/test_record_decisions.py)
   * **Діапазон рядків:** L1–L110 (новий файл)
   * **Зміни:** Створено ізольований тестовий fixture sample_orders_fixture для перевірки:
     * Формування рівно одного фінального статусу на рядок.
     * Акумуляції одночасно кількох помилок у список reason_codes.
     * Маркування статусу duplicate для точних бізнес-копій.

---

## [Завдання 4] Обмежений набір правил приймання (Load Policy)

* **Мета:** Реалізувати навчальний контракт валідації та типізації при перенесенні даних stg -> core, правила для дат (ISO 8601 + DD/MM/YYYY як UTC), валют (UAH, USD, EUR без виправлення 'UA H'), цін активних товарів, точних дублікатів та конфліктних груп ключів, сувору перевірку FK без мовчазного відкидання.
* **Дата:** 18.10.2026

### Змінені та створені файли:

1. [sql/lab02/01_create_schemas.sql](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/sql/lab02/01_create_schemas.sql)
   * **Діапазон рядків:** L38–L50
   * **Зміни:** Створено таблицю audit.rejected_records для збереження причин відхилення, деталей та сирого стану запису.
2. [src/lab02/load_core.py](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/src/lab02/load_core.py)
   * **Діапазон рядків:** L50–L105
   * **Зміни:**
     * Функція parse_acceptance_timestamp: приведення DD/MM/YYYY HH:MM до UTC; усічення наносекунд до мікросекунд.
     * Функція parse_numeric: парсинг numeric(12,2) без коерсії у 0.
     * Валідація ALLOWED_CURRENCIES = {'UAH', 'USD', 'EUR'} з відхиленням 'UA H'.
     * Відхилення активних товарів з ціною <= 0.
     * Відхилення конфліктних груп ключів з різними значеннями.
     * Логування розірваних зв'язків у audit.rejected_records.
3. [sql/lab02/05_transform_stg_to_core.sql](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/sql/lab02/05_transform_stg_to_core.sql)
   * **Діапазон рядків:** L1–L215 (новий файл)
   * **Зміни:** Процедурний PL/pgSQL скрипт трансформації даних засобами СУБД.
4. [tests/test_acceptance_rules.py](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/tests/test_acceptance_rules.py)
   * **Діапазон рядків:** L1–L66 (новий файл)
   * **Зміни:** Тести для перевірки контрактних правил приймання.
5. [docs/lab02/load_policy.md](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/docs/lab02/load_policy.md)
   * **Діапазон рядків:** L1–L135 (новий файл)
   * **Зміни:** Детальна документація обов'язкового контракту завантаження.

---

## [Завдання 1–3] Простори імен stg, core, audit та завантаження джерел у Staging

* **Мета:** Створити схеми stg, core, audit. Забезпечити збереження мінімальних полів у core, а решти колонок у staging без унікальності email. Реалізувати повторюваний імпорт через Python-драйвер / \copy, перевірку заголовків та порядку колонок, зупинку на зламаних файлах без втрати записів, параметризацію запитів.
* **Дата:** 18.10.2026

### Змінені та створені файли:

1. [sql/lab02/01_create_schemas.sql](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/sql/lab02/01_create_schemas.sql)
   * **Діапазон рядків:** L1–L37
   * **Зміни:** Створення схем stg, core, audit та таблиць аудиту пакетів audit.load_batches і завантажених файлів audit.load_files.
2. [sql/lab02/02_create_stg_tables.sql](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/sql/lab02/02_create_stg_tables.sql)
   * **Діапазон рядків:** L1–L185 (новий файл)
   * **Зміни:** DDL таблиць staging із метаданими batch_id, source_file, source_row_number, loaded_at та полями TEXT.
3. [sql/lab02/03_create_core_tables.sql](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/sql/lab02/03_create_core_tables.sql)
   * **Діапазон рядків:** L1–L68 (новий файл)
   * **Зміни:** DDL таблиць core.* з обмеженнями PK, FK та забороною UNIQUE на email.
4. [sql/lab02/04_load_staging_copy.sql](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/sql/lab02/04_load_staging_copy.sql)
   * **Діапазон рядків:** L1–L65 (новий файл)
   * **Зміни:** Скрипт завантаження через psql copy.
5. [src/lab02/config.py](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/src/lab02/config.py)
   * **Діапазон рядків:** L1–L190 (новий файл)
   * **Зміни:** Парсинг конфігурації з .env та словник STAGING_TABLES.
6. [src/lab02/load_staging.py](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/src/lab02/load_staging.py)
   * **Діапазон рядків:** L1–L325 (новий файл)
   * **Зміни:** Строга перевірка заголовків, параметризоване завантаження, аудит рядків.
7. [.env](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/.env) та [.env.example](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/.env.example)
   * **Діапазон рядків:** L1–L7
   * **Зміни:** Конфігурація підключення до БД.
8. [tests/test_staging_loader.py](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/tests/test_staging_loader.py)
   * **Діапазон рядків:** L1–L68 (новий файл)
   * **Зміни:** Автоматичні тести валідації імпорту в staging.
9. [docs/lab02/staging_architecture_and_loader.md](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/docs/lab02/staging_architecture_and_loader.md) та [docs/lab02/lab02_database_and_loader_guide.md](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/docs/lab02/lab02_database_and_loader_guide.md)
   * **Діапазон рядків:** L1–L265
   * **Зміни:** Повні звіти про розміщення бази даних та архітектуру staging.
