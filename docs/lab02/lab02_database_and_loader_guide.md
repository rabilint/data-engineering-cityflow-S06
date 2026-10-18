# Звіт та вичерпний посібник: База даних, архітектура шарів та робота завантажувача Staging (Лабораторна робота 2)

---

## 1. Де знаходиться база даних і як до неї підключитися

База даних розгорнута локально на вашому комп'ютері під керуванням **PostgreSQL 16**.

### Технічні параметри розміщення:
* **Хост:** `localhost` (або `127.0.0.1`)
* **Порт:** `5432`
* **Назва бази даних:** `cityflow_db`
* **Користувач-адміністратор:** `postgres`
* **Метод автентифікації:** `scram-sha-256` (пароль зберігається у захищеному локальному файлі [`.env`](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/.env))
* **Фізичне розташування файлів СУБД на диску:** `C:\Program Files\PostgreSQL\16\data`
* **Виконувані утиліти (CLI):** `C:\Program Files\PostgreSQL\16\bin\` (`psql.exe`, `createdb.exe` тощо)
* **Статус системної служби:** Служба Windows `postgresql-x64-16` працює у фоновому режимі (автозапуск).

### Способи підключення:

1. **Через термінал (psql):**
   ```powershell
   & "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -d cityflow_db -h localhost
   ```
2. **Через GUI-клієнт (pgAdmin 4 / DBeaver / DataGrip):**
   * Host: `localhost` | Port: `5432` | Database: `cityflow_db` | Username: `postgres`
3. **Через Python (psycopg2):**
   Параметри автоматично зчитуються модулем [`src/lab02/config.py`](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/src/lab02/config.py) із файлу [`.env`](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/.env).

---

## 2. Архітектура просторів імен (Schemas)

У базі даних `cityflow_db` розгорнуто 3 окремі схеми відповідно до сучасного підходу **ELT (Extract-Load-Transform)**:

```
 Первинні файли CSV
 (data/raw/base + relational)
            │
            ▼
┌────────────────────────────────────────────────────────┐
│                      Схема: stg                        │
│   - Зберігає 100% сирих даних без фільтрацій           │
│   - Усі бізнес-поля мають тип TEXT                     │
│   - Додано метадані: batch_id, source_file,            │
│     source_row_number, loaded_at                       │
│   - Жодних обмежень PK/FK/UNIQUE                       │
└────────────────────────────────────────────────────────┘
            │
            ▼ (наступний етап: очищення та валідація)
┌────────────────────────────────────────────────────────┐
│                      Схема: core                       │
│   - Очищена реляційна модель предметної області        │
│   - Строга типізація (VARCHAR, NUMERIC, TIMESTAMPTZ)   │
│   - Обмеження цілісності: PK, FK (REFERENCES), CHECK   │
│   - Мінімальний набір полів згідно зі специфікацією    │
│   - Email клієнта НЕ оголошено UNIQUE                  │
└────────────────────────────────────────────────────────┘
            │
            ▼ (паралельно)
┌────────────────────────────────────────────────────────┐
│                     Схема: audit                       │
│   - audit.load_batches : статус пакетів (SUCCESS/FAIL) │
│   - audit.load_files   : облік рядків прочитано/записано│
└────────────────────────────────────────────────────────┘
```

### Еквівалентний поділ в індустрії:
* **Medallion Architecture (Databricks / Delta Lake):**
  * `stg` ➔ **Bronze** (сирі дані з метаданими аудиту)
  * `core` ➔ **Silver** (валідована реляційна 3NF модель)
  * Вітрини звітів ➔ **Gold** (бізнес-агрегати)
* **Класичний Data Warehouse (Inmon):**
  * `stg` ➔ **Landing & Staging Area**
  * `core` ➔ **Enterprise Data Warehouse (EDW Core)**
  * `audit` ➔ **Metadata & Governance Layer**

---

## 3. Специфікація полів: `core` проти `staging`

Згідно з вимогами завдання, вихідні колонки розподілено так:

| Таблиця | Мінімальні поля у `core` (типізовані) | Додаткові поля, збережені у `stg` (TEXT) |
|---|---|---|
| **customers** | `customer_id`, `full_name`, `city`, `registered_at` | `email`, `phone`, `service_zone_id`, `customer_status` |
| **merchants** | `merchant_id`, `merchant_name`, `city`, `opened_at` | `merchant_type`, `service_zone_id`, `merchant_status` |
| **products** | `product_id`, `merchant_id`, `product_name`, `unit_price_uah`, `is_active` | `category`, `updated_at` |
| **orders** | `order_id`, `customer_id`, `merchant_id`, `created_at`, `order_status`, `currency`, `subtotal_amount`, `delivery_fee`, `discount_amount`, `total_amount` | *(усі 10 полів зберігаються у stg як TEXT)* |
| **order_items** | `order_item_id`, `order_id`, `product_id`, `quantity`, `unit_price`, `line_discount`, `line_total`, `currency` | *(усі 8 полів зберігаються у stg як TEXT)* |

### Чому `email` не оголошується унікальним (`UNIQUE`):
1. **Бізнес-правило:** Відсутнє підтверджене бізнес-визначення, що одна адреса пошти належить суворо одному обліковому запису.
2. **Фактичні аномалії даних (Data Profiling):** У файлі `customers.csv` акаунти `S06-C000270`, `S06-C000703` та `S06-C000360` мають однакову пошту. У реальних системах пошта часто використовується спільно членами родини або одним клієнтом для різних профілів. Додавання обмеження `UNIQUE` призвело б до падіння транзакції або відкидання клієнтів.

---

## 4. Як працює створений код (Архітектурний розбір)

Створено модульну структуру, що відповідає кращим практикам інженерії даних:

```
├── .env                       <- Робоча конфігурація підключення до PostgreSQL
├── .env.example               <- Шаблон конфігурації
├── sql/lab02/
│   ├── 01_create_schemas.sql  <- Створення схем stg, core, audit та таблиць аудиту
│   ├── 02_create_stg_tables.sql <- DDL таблиць stg з технічними метаданими
│   ├── 03_create_core_tables.sql<- DDL таблиць core зі зв'язками PK/FK
│   └── 04_load_staging_copy.sql <- Альтернативний скрипт імпорту через psql \copy
├── src/lab02/
│   ├── config.py              <- Читання .env, шляхи до CSV, еталонні схеми колонок
│   └── load_staging.py        <- Основний ETL-пайплайн завантаження у Staging
├── tests/
│   └── test_staging_loader.py <- Автоматичні юніт-тести валідації та цілісності
└── docs/lab02/
    ├── staging_architecture_and_loader.md <- Технічний опис архітектури
    └── lab02_database_and_loader_guide.md  <- Цей вичерпний звіт
```

### Детальний алгоритм роботи [`src/lab02/load_staging.py`](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/src/lab02/load_staging.py):

1. **Ініціалізація пакета (Batch Registration):**
   * Створюється унікальний ідентифікатор сесії: `batch_YYYYMMDD_HHMMSS_<hash>` (наприклад, `batch_20261018_170956_1c3081`).
   * У таблицю `audit.load_batches` записується запис зі статусом `'RUNNING'`.
2. **Явна перевірка заголовка та порядку колонок (`validate_csv_header`):**
   * Зчитується перший рядок CSV-файлу.
   * Виконується строге поелементне порівняння з еталонним списком:
     ```python
     if clean_actual != clean_expected:
         raise StructuralValidationError(...)
     ```
   * Якщо хоча б одну колонку пропущено, перейменовано або переставлено місцями — процес негайно зупиняється до того, як будь-які дані потраплять у БД.
3. **Порядковий контроль структури рядків (`read_and_validate_csv`):**
   * Жодного мовчазного пропуску зламаних рядків (`on_bad_lines='skip'` суворо заборонено).
   * Якщо в рядку `N` кількість значень не дорівнює очікуваній кількості колонок, генерується помилка:
     `Structurally broken file at row N: expected X columns, found Y`.
   * Генерується лічильник `source_row_number`, який починається з **1** для першого запису даних після заголовка (це фізичний номер рядка у вихідному файлі, а не бізнес-ключ).
   * До кожного рядка прикріплюються метадані: `(batch_id, source_file, source_row_number, loaded_at, *business_fields)`.
4. **Транзакційний параметризований запис (`load_file_to_staging`):**
   * Запис здійснюється блоками через `psycopg2.extras.execute_values` з використанням параметризованих плейсхолдерів `%s`.
   * **Жодної конкатенації рядків SQL** (`f"INSERT INTO ... VALUES ('{val}')"` не використовується), що гарантує захист від SQL-ін'єкцій та коректну обробку лапок, апострофів і спецсимволів.
5. **Верифікація збереження 100% рядків (Zero Data Loss):**
   * Після вставки кожного файлу виконується контрольний запит:
     ```sql
     SELECT COUNT(*) FROM stg.<table_name> WHERE batch_id = %s;
     ```
   * Кількість у БД має з точністю до одного збігатися з кількістю прочитаних рядків у CSV (`loaded_count == row_count`).
6. **Запис у журнал аудиту та фіксація транзакції (Commit):**
   * Статистика завантаження кожного файлу записується в `audit.load_files`.
   * Якщо всі таблиці завантажено без помилок, статус пакета в `audit.load_batches` оновлюється на `'SUCCESS'`, і транзакція фіксується `conn.commit()`.
   * Якщо сталася будь-яка помилка, викликається `conn.rollback()`, а пакет маркується як `'FAILED'` із збереженням тексту помилки.

---

## 5. Фактичні результати роботи завантажувача

Пайплайн успішно виконано в повному обсязі.

### 1. Звіт завантаження за таблицями:

| Вихідний CSV-файл | Цільова таблиця | Прочитано рядків CSV | Завантажено в Staging | Втрата рядків | Статус |
|---|---|:---:|:---:|:---:|:---:|
| `data/raw/base/customers.csv` | `stg.customers` | **801** | **801** | **0** | `SUCCESS` |
| `data/raw/base/merchants.csv` | `stg.merchants` | **43** | **43** | **0** | `SUCCESS` |
| `data/raw/base/products.csv` | `stg.products` | **504** | **504** | **0** | `SUCCESS` |
| `data/raw/base/orders.csv` | `stg.orders` | **6 001** | **6 001** | **0** | `SUCCESS` |
| `data/raw/relational/order_items.csv` | `stg.order_items` | **13 861** | **13 861** | **0** | `SUCCESS` |
| **Разом:** | | **21 210** | **21 210** | **0** | **УСПІШНО** |

*Час виконання завантаження всіх 21 210 рядків склав менше 0.7 секунди.*

### 2. Стан таблиць аудиту в базі даних:

* **Запис у `audit.load_batches`:**
  ```sql
  SELECT batch_id, started_at, completed_at, status, created_by FROM audit.load_batches;
  ```
  ```
             batch_id           |          started_at           |         completed_at          | status  | created_by 
  ------------------------------+-------------------------------+-------------------------------+---------+------------
   batch_20261018_170956_1c3081 | 2026-10-18 20:09:56.301449+03 | 2026-10-18 20:09:56.909964+03 | SUCCESS | postgres
  ```

* **Записи у `audit.load_files`:**
  ```sql
  SELECT source_file, target_table, rows_read, rows_loaded, status FROM audit.load_files;
  ```
  ```
     source_file   |  target_table   | rows_read | rows_loaded | status  
  -----------------+-----------------+-----------+-------------+---------
   customers.csv   | stg.customers   |       801 |         801 | SUCCESS
   merchants.csv   | stg.merchants   |        43 |          43 | SUCCESS
   products.csv    | stg.products    |       504 |         504 | SUCCESS
   orders.csv      | stg.orders      |      6001 |        6001 | SUCCESS
   order_items.csv | stg.order_items |     13861 |       13861 | SUCCESS
  ```

### 3. Реальний зріз збережених рядків із метаданими:

* **`stg.customers`:**
  ```sql
  SELECT source_row_number, customer_id, full_name, city, email, loaded_at 
  FROM stg.customers LIMIT 3;
  ```
  ```
   source_row_number | customer_id |     full_name     |  city   |              email              |           loaded_at           
  -------------------+-------------+-------------------+---------+---------------------------------+-------------------------------
                   1 | S06-C000001 | Roman Moroz       | Kyiv    | s06.customer000001@example.test | 2026-10-18 20:09:56.305346+03
                   2 | S06-C000002 | Natalia Kovalchuk | Lviv    | s06.customer000002@example.test | 2026-10-18 20:09:56.305346+03
                   3 | S06-C000003 | Viktor Oliinyk    | Kharkiv | s06.customer000003@example.test | 2026-10-18 20:09:56.305346+03
  ```

* **`stg.orders`:**
  ```sql
  SELECT source_row_number, order_id, customer_id, total_amount, currency, order_status 
  FROM stg.orders LIMIT 3;
  ```
  ```
   source_row_number |   order_id   | customer_id | total_amount | currency | order_status 
  -------------------+--------------+-------------+--------------+----------+--------------
                   1 | S06-O0000001 | S06-C000793 | 176.57       | UAH      | delivered
                   2 | S06-O0000002 | S06-C000377 | 1778.5       | UAH      | delivered
                   3 | S06-O0000003 | S06-C000178 | 1049.04      | UAH      | delivered
  ```

---

## 6. Результати виконання юніт-тестів

Для перевірки граничних випадків та надійності створено набір тестів у [`tests/test_staging_loader.py`](file:///c:/Users/Rabil/Desktop/%D1%83%D0%BD%D1%96%D0%BA/3%D0%BA/%D0%9C%D0%B5%D1%82%D0%BE%D0%B4%D0%B8%20%D1%82%D0%B0%20%D1%82%D0%B5%D1%85%D0%BD%D0%BE%D0%BB%D0%BE%D0%B3%D1%96%D1%97%20%D1%96%D0%BD%D0%B6%D0%B5%D0%BD%D0%B5%D1%80%D1%96%D1%97%20%D0%B4%D0%B0%D0%BD%D0%B8%D1%85/tests/test_staging_loader.py):

* `test_validate_csv_header_success`: перевірка проходження валідного заголовка.
* `test_validate_csv_header_reordered_fails`: блокування файлу, якщо порядок колонок порушено.
* `test_validate_csv_header_missing_column_fails`: блокування файлу, якщо пропущено колонку.
* `test_read_and_validate_csv_success_and_metadata`: перевірка коректності генерації `batch_id`, `loaded_at` та 1-based нумерації `source_row_number`.
* `test_read_and_validate_csv_broken_row_fails_immediately`: перевірка миттєвої зупинки на рядку з некоректною кількістю колонок (жодного пропуску рядків).

**Результат запуску тестів:**
```
============================== 5 passed in 0.09s ==============================
```

---

## 7. Команди для повторного запуску та перевірки

```powershell
# 1. Валідація файлів без звернення до БД (Dry-Run):
.venv\Scripts\python -m src.lab02.load_staging --dry-run

# 2. Запуск тестів:
.venv\Scripts\python -m pytest tests/test_staging_loader.py -v

# 3. Повторне завантаження у Staging (додасть новий пакет у БД):
.venv\Scripts\python -m src.lab02.load_staging

# 4. Перезавантаження Staging з очищенням таблиць (Truncate & Reload):
.venv\Scripts\python -m src.lab02.load_staging --truncate

# 5. Завантаження всіх 10 таблиць (включно з couriers, deliveries, payments тощо):
.venv\Scripts\python -m src.lab02.load_staging --all-tables
```
