-- ==============================================================================
-- Лабораторна робота 2: Створення просторів імен (схем) та таблиць аудиту
-- ==============================================================================

-- 1. Створення просторів імен (схем)
-- stg   : рівень сирих даних (staging), де зберігаються вихідні дані у вихідному форматі (TEXT) з метаданими
-- core  : рівень очищених, типізованих бізнес-сутностей з первинними та зовнішніми ключами
-- audit : рівень технічного моніторингу, аудиту завантажень, пакетів та контролю якості
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS audit;

-- 2. Таблиці для аудиту завантажень (audit schema)

-- Журнал пакетів завантаження (batches)
CREATE TABLE IF NOT EXISTS audit.load_batches (
    batch_id VARCHAR(64) PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED')),
    error_message TEXT,
    created_by VARCHAR(100) DEFAULT current_user
);

-- Журнал файлів, завантажених у межах пакетів
CREATE TABLE IF NOT EXISTS audit.load_files (
    file_load_id BIGSERIAL PRIMARY KEY,
    batch_id VARCHAR(64) NOT NULL REFERENCES audit.load_batches(batch_id) ON DELETE CASCADE,
    source_file TEXT NOT NULL,
    target_table TEXT NOT NULL,
    rows_read BIGINT NOT NULL DEFAULT 0,
    rows_loaded BIGINT NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL CHECK (status IN ('SUCCESS', 'FAILED')),
    error_message TEXT,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Журнал відхилених записів (аудит контролю якості та зв'язків)
CREATE TABLE IF NOT EXISTS audit.rejected_records (
    rejection_id BIGSERIAL PRIMARY KEY,
    batch_id VARCHAR(64) NOT NULL,
    source_table TEXT NOT NULL,
    source_row_number BIGINT,
    entity_id TEXT,
    rejection_reason TEXT NOT NULL,
    details TEXT,
    raw_record JSONB,
    rejected_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Журнал рішень для кожного вихідного запису (Завдання 5: accepted, rejected, duplicate)
CREATE TABLE IF NOT EXISTS audit.record_decisions (
    decision_id BIGSERIAL PRIMARY KEY,
    batch_id VARCHAR(64) NOT NULL,
    source_file TEXT NOT NULL,
    source_row_number BIGINT NOT NULL,
    business_key TEXT,
    final_status VARCHAR(20) NOT NULL CHECK (final_status IN ('accepted', 'rejected', 'duplicate')),
    reason_codes TEXT[] NOT NULL DEFAULT '{}',
    details TEXT,
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Індекси для прискорення пошуку в аудиті
CREATE INDEX IF NOT EXISTS idx_load_files_batch_id ON audit.load_files(batch_id);
CREATE INDEX IF NOT EXISTS idx_load_files_target_table ON audit.load_files(target_table);
CREATE INDEX IF NOT EXISTS idx_rejected_records_batch_id ON audit.rejected_records(batch_id);
CREATE INDEX IF NOT EXISTS idx_rejected_records_source_table ON audit.rejected_records(source_table);
CREATE INDEX IF NOT EXISTS idx_rejected_records_reason ON audit.rejected_records(rejection_reason);
CREATE INDEX IF NOT EXISTS idx_record_decisions_batch ON audit.record_decisions(batch_id);
CREATE INDEX IF NOT EXISTS idx_record_decisions_file_row ON audit.record_decisions(source_file, source_row_number);
CREATE INDEX IF NOT EXISTS idx_record_decisions_status ON audit.record_decisions(final_status);

-- 3. Журнал спроб публікації та звірки (Завдання 6 & 7)

-- Журнал спроб публікації (run_id, batch_id, started_at, finished_at, status)
CREATE TABLE IF NOT EXISTS audit.publication_runs (
    run_id VARCHAR(64) PRIMARY KEY,
    batch_id VARCHAR(64) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    finished_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED')),
    reconciliation_passed BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    created_by VARCHAR(100) DEFAULT current_user
);

-- Пофайловий баланс та звірка кількості й ключів (input = accepted + rejected + duplicate, core vs accepted)
CREATE TABLE IF NOT EXISTS audit.publication_run_files (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL REFERENCES audit.publication_runs(run_id) ON DELETE CASCADE,
    source_file TEXT NOT NULL,
    target_table TEXT NOT NULL,
    input_count BIGINT NOT NULL,
    accepted_count BIGINT NOT NULL,
    rejected_count BIGINT NOT NULL,
    duplicate_count BIGINT NOT NULL,
    balance_valid BOOLEAN NOT NULL DEFAULT FALSE,
    core_count_match BOOLEAN NOT NULL DEFAULT FALSE,
    core_keys_match BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- Фінансова звірка сум orders.total_amount та order_items.line_total за валютами (staging accepted vs core)
CREATE TABLE IF NOT EXISTS audit.financial_reconciliation (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(64) NOT NULL REFERENCES audit.publication_runs(run_id) ON DELETE CASCADE,
    currency VARCHAR(10) NOT NULL,
    stg_orders_total NUMERIC(16, 2) NOT NULL,
    core_orders_total NUMERIC(16, 2) NOT NULL,
    orders_diff NUMERIC(16, 2) NOT NULL,
    stg_items_line_total NUMERIC(16, 2) NOT NULL,
    core_items_line_total NUMERIC(16, 2) NOT NULL,
    items_diff NUMERIC(16, 2) NOT NULL,
    matched BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS idx_publication_runs_batch_id ON audit.publication_runs(batch_id);
CREATE INDEX IF NOT EXISTS idx_publication_runs_status ON audit.publication_runs(status);
CREATE INDEX IF NOT EXISTS idx_pub_run_files_run_id ON audit.publication_run_files(run_id);
CREATE INDEX IF NOT EXISTS idx_financial_recon_run_id ON audit.financial_reconciliation(run_id);

