-- Particionamiento por rango de fechas
CREATE TABLE transacciones_log_2023_s1 PARTITION OF transacciones_log
    FOR VALUES FROM ('2023-01-01') TO ('2023-07-01');

CREATE TABLE transacciones_log_2023_s2 PARTITION OF transacciones_log
    FOR VALUES FROM ('2023-07-01') TO ('2024-01-01');

CREATE TABLE transacciones_log_2024_s1 PARTITION OF transacciones_log
    FOR VALUES FROM ('2024-01-01') TO ('2024-07-01');

CREATE TABLE transacciones_log_2024_s2 PARTITION OF transacciones_log
    FOR VALUES FROM ('2024-07-01') TO ('2025-01-01');

CREATE TABLE transacciones_log_2025 PARTITION OF transacciones_log
    FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');

-- Verificar
SELECT inhrelid::regclass AS particion
FROM pg_inherits
WHERE inhparent = 'transacciones_log'::regclass;
---------------------------------------------------------------------------
-- Particionamiento hash por id_usuario
CREATE TABLE transacciones_log_hash (
    id          BIGSERIAL,
    id_usuario  INT NOT NULL,
    tipo        VARCHAR(50) NOT NULL,
    monto       NUMERIC(12,2) NOT NULL,
    fecha       TIMESTAMP NOT NULL DEFAULT NOW(),
    nodo_origen VARCHAR(20) DEFAULT 'nodo1'
) PARTITION BY HASH (id_usuario);

CREATE TABLE transacciones_log_hash_0 PARTITION OF transacciones_log_hash
    FOR VALUES WITH (MODULUS 3, REMAINDER 0);

CREATE TABLE transacciones_log_hash_1 PARTITION OF transacciones_log_hash
    FOR VALUES WITH (MODULUS 3, REMAINDER 1);

CREATE TABLE transacciones_log_hash_2 PARTITION OF transacciones_log_hash
    FOR VALUES WITH (MODULUS 3, REMAINDER 2);