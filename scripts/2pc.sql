-- ============================================
-- PROYECTO 2 - BDD AVANZADAS
-- Script: Transacciones Distribuidas 2PC
-- Responsable: Isabella
-- Dominio: Ecommerce (ShopFast)
-- ============================================

-- PRERREQUISITO: max_prepared_transactions debe ser > 0
-- Verificar con:
SHOW max_prepared_transactions;

-- Si está en 0, ejecutar:
-- ALTER SYSTEM SET max_prepared_transactions = 10;
-- Luego reiniciar PostgreSQL:
-- net stop postgresql-x64-17
-- net start postgresql-x64-17

-- ============================================
-- ESCENARIO: Compra que afecta dos nodos
-- Nodo 1: descuenta stock del producto
-- Nodo 2: registra el pago
-- ============================================

-- FASE 1 — PREPARE
-- Ambos nodos se preparan para confirmar.
-- En este punto los cambios están escritos en el WAL
-- pero NO son visibles para otras transacciones.

-- Nodo 1: descontar stock
BEGIN;
UPDATE productos SET stock = stock - 1 WHERE id = 1;
PREPARE TRANSACTION 'txn_compra_nodo1';

-- Nodo 2: registrar pago
BEGIN;
INSERT INTO pagos (id_pedido, monto, metodo, fecha)
VALUES (1, 150.00, 'tarjeta', NOW());
PREPARE TRANSACTION 'txn_compra_nodo2';

-- FASE 2 — COMMIT
-- El coordinador confirma ambos nodos.
-- Solo cuando ambos confirman, los cambios son visibles.

COMMIT PREPARED 'txn_compra_nodo1';
COMMIT PREPARED 'txn_compra_nodo2';

-- VERIFICACIÓN
SELECT stock FROM productos WHERE id = 1;
SELECT * FROM pagos ORDER BY id DESC LIMIT 1;

-- ============================================
-- ESCENARIO DE FALLO DEL COORDINADOR
-- El coordinador cae después del PREPARE
-- y antes del COMMIT
-- ============================================

-- El coordinador prepara la transacción...
BEGIN;
UPDATE productos SET stock = stock - 1 WHERE id = 1;
PREPARE TRANSACTION 'txn_fallo_test';

-- ...aquí el coordinador se cae.
-- El COMMIT nunca se ejecuta.

-- Verificar que la transacción quedó colgada:
SELECT gid, prepared, owner FROM pg_prepared_xacts;
-- Resultado: txn_fallo_test aparece colgada
-- Los recursos están BLOQUEADOS indefinidamente

-- ============================================
-- RESOLUCIÓN MANUAL POR EL DBA
-- ============================================

-- El DBA detecta transacciones colgadas:
SELECT gid, prepared, owner FROM pg_prepared_xacts;

-- Opción 1: confirmar
-- (si el DBA sabe que el coordinador había terminado correctamente)
COMMIT PREPARED 'txn_fallo_test';

-- Opción 2: revertir
-- (si el DBA no tiene certeza del estado)
-- ROLLBACK PREPARED 'txn_fallo_test';

-- Verificar que desapareció:
SELECT gid FROM pg_prepared_xacts;
-- (0 filas) = ya no hay transacciones colgadas

-- Verificar el stock final:
SELECT stock FROM productos WHERE id = 1;