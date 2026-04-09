**SI3009 Bases de Datos Avanzadas, 2026-1**  
**Ingeniería de Sistemas**  
**Equipo:** Isabella · Juan José · Nicolás

---

## Tabla de Contenido

1. [Contexto del Problema](#contexto)
2. [Modelo de Datos](#modelo)
3. [Volúmenes Estimados](#volumenes)
4. [Operaciones OLTP y OLAP](#operaciones)
5. [Parte 1 — Isabella: PostgreSQL Particionamiento y 2PC](#parte1)
   - [Ambiente de trabajo](#ambiente)
   - [Particionamiento por Rango](#rango)
   - [Particionamiento por Hash](#hash)
   - [EXPLAIN ANALYZE](#explain)
   - [Transacciones Distribuidas 2PC](#2pc)
   - [Escenario de fallo del coordinador](#fallo)
6. [Parte 2 — Juan José: PostgreSQL Replicación, Failover y Experimentos](#parte2)
7. [Parte 3 — Nicolás: NewSQL y Análisis Comparativo](#parte3)
8. [Comparación Final PostgreSQL vs NewSQL](#comparacion)
9. [Análisis Crítico](#critico)
10. [Conclusiones](#conclusiones)

---

## 1. Contexto del Problema <a name="contexto"></a>

La empresa ficticia **ShopFast** es una plataforma de ecommerce colombiana que opera a nivel nacional, permitiendo a usuarios comprar productos de categorías como ropa, electrónica, hogar y alimentos.

El sistema maneja miles de transacciones diarias distribuidas entre usuarios de diferentes regiones del país (norte, sur, centro e internacional). A medida que la plataforma crece, una base de datos centralizada se convierte en un cuello de botella: las consultas analíticas compiten con las transaccionales, los tiempos de respuesta aumentan y la disponibilidad se ve comprometida.

Por esto se diseña una arquitectura distribuida que permita:
- Escalar horizontalmente el volumen de transacciones
- Aislar la carga OLTP de la OLAP mediante particionamiento
- Garantizar disponibilidad ante fallos de nodos individuales
- Mantener consistencia en operaciones críticas como pagos y pedidos

### Diagrama de Arquitectura General

> <img width="1929" height="675" alt="image" src="https://github.com/user-attachments/assets/c61c6b7b-d9f5-4e50-a4ae-6050716ead41" />


---

## 2. Modelo de Datos <a name="modelo"></a>

El dominio es **Ecommerce**. Se definieron 5 tablas que cubren los procesos principales de la plataforma.

### Diagrama entidad-relación

```
usuarios (id, nombre, email, region, creado_en)
    │
    └──► pedidos (id, id_usuario, fecha, estado, total)
              │
              └──► pagos (id, id_pedido, monto, metodo, fecha, estado)

productos (id, nombre, categoria, precio, stock)

transacciones_log (id, id_usuario, tipo, monto, fecha, nodo_origen)
└── particionada por RANGO (fecha) → 5 particiones semestrales

transacciones_log_hash (id, id_usuario, tipo, monto, fecha, nodo_origen)
└── particionada por HASH (id_usuario) → 3 particiones por nodo
```

### Script de creación de tablas

```sql
DROP TABLE IF EXISTS transacciones_log CASCADE;
DROP TABLE IF EXISTS pagos CASCADE;
DROP TABLE IF EXISTS pedidos CASCADE;
DROP TABLE IF EXISTS productos CASCADE;
DROP TABLE IF EXISTS usuarios CASCADE;

CREATE TABLE usuarios (
    id         SERIAL PRIMARY KEY,
    nombre     VARCHAR(100) NOT NULL,
    email      VARCHAR(150) UNIQUE NOT NULL,
    region     VARCHAR(50) NOT NULL,
    creado_en  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE productos (
    id         SERIAL PRIMARY KEY,
    nombre     VARCHAR(200) NOT NULL,
    categoria  VARCHAR(80) NOT NULL,
    precio     NUMERIC(10,2) NOT NULL,
    stock      INT NOT NULL DEFAULT 0
);

CREATE TABLE pedidos (
    id         SERIAL PRIMARY KEY,
    id_usuario INT NOT NULL REFERENCES usuarios(id),
    fecha      TIMESTAMP NOT NULL DEFAULT NOW(),
    estado     VARCHAR(30) NOT NULL DEFAULT 'pendiente',
    total      NUMERIC(12,2) NOT NULL
);

CREATE TABLE pagos (
    id         SERIAL PRIMARY KEY,
    id_pedido  INT NOT NULL REFERENCES pedidos(id),
    monto      NUMERIC(12,2) NOT NULL,
    metodo     VARCHAR(50) NOT NULL,
    fecha      TIMESTAMP NOT NULL DEFAULT NOW(),
    estado     VARCHAR(30) NOT NULL DEFAULT 'aprobado'
);

CREATE TABLE transacciones_log (
    id          BIGSERIAL,
    id_usuario  INT NOT NULL,
    tipo        VARCHAR(50) NOT NULL,
    monto       NUMERIC(12,2) NOT NULL,
    fecha       TIMESTAMP NOT NULL DEFAULT NOW(),
    nodo_origen VARCHAR(20) DEFAULT 'nodo1'
) PARTITION BY RANGE (fecha);
```

---

## 3. Volúmenes Estimados <a name="volumenes"></a>

| Tabla | Registros generados | Proyección real (1 año) | Crecimiento mensual |
|---|---:|---:|---:|
| usuarios | 1.000 | ~500.000 | ~15.000 |
| productos | 200 | ~10.000 | ~300 |
| pedidos | 5.000 | ~2.000.000 | ~150.000 |
| pagos | 5.000 | ~2.000.000 | ~150.000 |
| transacciones_log | 500.000 | ~50.000.000 | ~4.000.000 |

Los datos sintéticos cubren un período de 2 años (2023–2024) con distribución uniforme de fechas y regiones. Se usó la librería `psycopg2` de Python para inserción por lotes de 5.000 registros, logrando insertar 500k registros en menos de 5 minutos en una máquina local.

---

## 4. Operaciones OLTP y OLAP <a name="operaciones"></a>

### Operaciones OLTP (transaccionales — tiempo real, alta frecuencia)

| Operación | Tablas involucradas | Descripción |
|---|---|---|
| Registrar pedido | pedidos, transacciones_log | Usuario confirma una compra |
| Procesar pago | pagos, transacciones_log | Registro del pago asociado al pedido |
| Actualizar stock | productos | Descuento de unidades al confirmar compra |
| Consultar estado de pedido | pedidos | Usuario revisa si su pedido fue aprobado |
| Registrar devolución | transacciones_log, pagos | Reembolso de un pedido cancelado |

> Estas operaciones son candidatas al particionamiento por **hash (id_usuario)** para distribuir la carga entre nodos y garantizar que cada usuario siempre sea atendido por el mismo nodo.

### Operaciones OLAP (analíticas — periódicas, alta complejidad)

| Operación | Tablas involucradas | Descripción |
|---|---|---|
| Ventas totales por período | transacciones_log, pedidos | Reporte mensual/trimestral de ingresos |
| Top usuarios por monto | transacciones_log, usuarios | Ranking de clientes más valiosos |
| Productos más vendidos | pedidos, productos | Análisis de catálogo por categoría |
| Transacciones por región | transacciones_log, usuarios | Distribución geográfica de ventas |
| Tasa de devoluciones | transacciones_log | % de pedidos reembolsados por período |

> Estas operaciones se benefician del particionamiento por **rango (fecha)**, ya que los reportes siempre filtran por período de tiempo, permitiendo que PostgreSQL aplique *partition pruning*.

---

## 5. Parte 1 — Isabella: PostgreSQL Particionamiento y 2PC <a name="parte1"></a>

### Ambiente de trabajo <a name="ambiente"></a>

| Componente | Detalle |
|---|---|
| Motor | PostgreSQL 17.6 |
| Sistema operativo | Windows 10 |
| Herramientas | SQL Shell (psql), pgAdmin 4, Python 3.13 |
| Base de datos | `ecommerce_p2` |

**Conexión y creación de la base de datos:**

```sql
CREATE DATABASE ecommerce_p2;
\c ecommerce_p2
```

---

### Datos Sintéticos (`/scripts/generar_datos.py`)

```python
import psycopg2
import random
from datetime import datetime, timedelta

conn = psycopg2.connect(
    host="localhost", port=5432,
    database="ecommerce_p2", user="postgres", password="TU_CONTRASEÑA"
)
cur = conn.cursor()

regiones = ['norte', 'sur', 'centro', 'internacional']
for i in range(1, 1001):
    cur.execute("INSERT INTO usuarios (nombre, email, region) VALUES (%s, %s, %s)",
                (f"Usuario {i}", f"user{i}@mail.com", random.choice(regiones)))
conn.commit()

categorias = ['ropa', 'electronica', 'hogar', 'comida']
for i in range(1, 201):
    cur.execute("INSERT INTO productos (nombre, categoria, precio, stock) VALUES (%s, %s, %s, %s)",
                (f"Producto {i}", random.choice(categorias),
                 round(random.uniform(5, 500), 2), random.randint(0, 1000)))
conn.commit()

estados_pedido = ['pendiente', 'pagado', 'enviado', 'cancelado']
metodos_pago = ['tarjeta', 'pse', 'efectivo', 'cripto']
fecha_inicio = datetime(2023, 1, 1)

for i in range(1, 5001):
    id_usuario = random.randint(1, 1000)
    fecha = fecha_inicio + timedelta(days=random.randint(0, 730))
    total = round(random.uniform(10, 2000), 2)
    cur.execute("INSERT INTO pedidos (id_usuario, fecha, estado, total) VALUES (%s,%s,%s,%s) RETURNING id",
                (id_usuario, fecha, random.choice(estados_pedido), total))
    id_pedido = cur.fetchone()[0]
    cur.execute("INSERT INTO pagos (id_pedido, monto, metodo, fecha) VALUES (%s,%s,%s,%s)",
                (id_pedido, total, random.choice(metodos_pago), fecha))
    if i % 500 == 0:
        conn.commit()

conn.commit()

tipos = ['compra', 'devolucion', 'pago', 'reembolso']
nodos = ['nodo1', 'nodo2', 'nodo3']
batch = []

for i in range(500000):
    fecha = fecha_inicio + timedelta(days=random.randint(0, 730))
    batch.append((random.randint(1, 1000), random.choice(tipos),
                  round(random.uniform(1, 3000), 2), fecha, random.choice(nodos)))
    if len(batch) == 5000:
        cur.executemany(
            "INSERT INTO transacciones_log (id_usuario, tipo, monto, fecha, nodo_origen) VALUES (%s,%s,%s,%s,%s)",
            batch)
        conn.commit()
        batch = []

cur.close()
conn.close()
```

**Ejecución:**
```cmd
pip install psycopg2-binary
python generar_datos.py
```

---

### Particionamiento por Rango (fecha) <a name="rango"></a>

**¿Por qué rango?** Las consultas de ecommerce más frecuentes son por período de tiempo — reportes mensuales, auditorías, análisis de ventas. El rango permite *partition pruning* automático.

**Script (`/scripts/particionamiento.sql`):**

```sql
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
```

**Resultado:**

```
         particion
---------------------------
 transacciones_log_2023_s1
 transacciones_log_2023_s2
 transacciones_log_2024_s1
 transacciones_log_2024_s2
 transacciones_log_2025
(5 filas)
```

**Distribución de datos:**

```
         particion         | filas_aprox
---------------------------+-------------
 transacciones_log_2023_s1 |      123.632
 transacciones_log_2023_s2 |      125.859
 transacciones_log_2024_s1 |      124.229
 transacciones_log_2024_s2 |      126.280
 transacciones_log_2025    |           0
```

> <img width="443" height="922" alt="image" src="https://github.com/user-attachments/assets/31404ddb-476b-4872-a27a-589387823913" />


---

### Particionamiento por Hash (id_usuario) <a name="hash"></a>

**¿Por qué hash?** Distribuye la carga uniformemente entre nodos cuando no hay criterio de rango natural. Cada usuario siempre cae en el mismo nodo.

```sql
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
```

**Resultado:**

```
        particion
--------------------------
 transacciones_log_hash_0
 transacciones_log_hash_1
 transacciones_log_hash_2
(3 filas)
```

**¿Cómo sabe la aplicación en qué nodo está el dato?**

| Tipo | Mecanismo de enrutamiento |
|---|---|
| Rango (fecha) | La app evalúa la fecha y enruta al nodo correspondiente |
| Hash (id_usuario) | PostgreSQL calcula `hash(id_usuario) % 3` internamente — transparente para la app |
| NewSQL | Completamente automático — el motor maneja el enrutamiento sin configuración manual |

---

### EXPLAIN ANALYZE — Partition Pruning <a name="explain"></a>

#### Consulta 1 — Filtro por fecha (una sola partición)

```sql
EXPLAIN ANALYZE
SELECT * FROM transacciones_log
WHERE fecha BETWEEN '2023-01-01' AND '2023-06-30'
  AND tipo = 'compra';
```

**Resultado:**

> PostgreSQL escaneó **únicamente** `transacciones_log_2023_s1` — ignoró las otras 4 particiones completamente.

> <img width="921" height="605" alt="image" src="https://github.com/user-attachments/assets/a074cc29-1a34-4935-987c-b544898ecfb6" />
> <img width="681" height="478" alt="image" src="https://github.com/user-attachments/assets/c971b830-e65b-4ba5-958d-c370db3a44b2" />





#### Consulta 2 — JOIN distribuido con usuarios

```sql
EXPLAIN ANALYZE
SELECT u.nombre, u.region, COUNT(t.id) AS total_transacciones, SUM(t.monto) AS monto_total
FROM transacciones_log t
JOIN usuarios u ON t.id_usuario = u.id
WHERE t.fecha BETWEEN '2024-01-01' AND '2024-06-30'
GROUP BY u.nombre, u.region
ORDER BY monto_total DESC
LIMIT 10;
```

**Resultado:**

> Partition pruning activo — solo tocó `transacciones_log_2024_s1`.  
> Hash Inner Join + Parallel Seq Scan con 2 workers — PostgreSQL usó paralelismo automáticamente.

> <img width="914" height="849" alt="image" src="https://github.com/user-attachments/assets/033f4896-c8a0-46ef-a715-1b7e40821afb" />
> <img width="1267" height="416" alt="image" src="https://github.com/user-attachments/assets/24ce0885-022a-4a70-9e9b-42ed12e812d7" />


---

### Transacciones Distribuidas 2PC (`/scripts/2pc.sql`) <a name="2pc"></a>

#### Configuración previa

```sql
-- Habilitar max_prepared_transactions
ALTER SYSTEM SET max_prepared_transactions = 10;
```

```cmd
-- Reiniciar el servicio (CMD como administrador)
net stop postgresql-x64-17
net start postgresql-x64-17
```

```sql
-- Verificar
SHOW max_prepared_transactions;
-- Resultado: 10
```

#### Escenario: compra que afecta dos nodos

- **Nodo 1:** descontar stock del producto comprado
- **Nodo 2:** registrar el pago en la tabla de pagos

**Fase 1 — PREPARE (ambos nodos se preparan):**

```sql
-- Nodo 1
BEGIN;
UPDATE productos SET stock = stock - 1 WHERE id = 1;
PREPARE TRANSACTION 'txn_compra_nodo1';

-- Nodo 2
BEGIN;
INSERT INTO pagos (id_pedido, monto, metodo, fecha)
VALUES (1, 150.00, 'tarjeta', NOW());
PREPARE TRANSACTION 'txn_compra_nodo2';
```

**Fase 2 — COMMIT (el coordinador confirma todo):**

```sql
COMMIT PREPARED 'txn_compra_nodo1';
COMMIT PREPARED 'txn_compra_nodo2';
```

**Verificación:**

```sql
SELECT stock FROM productos WHERE id = 1;
-- stock: 20 ✅ (se descontó 1)

SELECT * FROM pagos ORDER BY id DESC LIMIT 1;
-- id: 5001 | monto: 150.00 | metodo: tarjeta | estado: aprobado ✅
```

---

### Escenario de Fallo del Coordinador <a name="fallo"></a>

**¿Qué pasa si el coordinador cae después del PREPARE y antes del COMMIT?**

```sql
-- El coordinador prepara la transacción...
BEGIN;
UPDATE productos SET stock = stock - 1 WHERE id = 1;
PREPARE TRANSACTION 'txn_fallo_test';

-- ...y se cae aquí. No se ejecuta el COMMIT.

-- Verificar que la transacción quedó colgada:
SELECT gid, prepared, owner FROM pg_prepared_xacts;
```

**Resultado:**

```
      gid       |           prepared            |  owner
----------------+-------------------------------+----------
 txn_fallo_test | 2026-04-08 22:11:16.969226-05 | postgres
(1 fila)
```

> <img width="1106" height="963" alt="image" src="https://github.com/user-attachments/assets/64148d6c-32d9-415e-a0cd-899a6e0b9af0" />


**Consecuencias:**

| Consecuencia | Descripción |
|---|---|
| Recursos bloqueados | El registro del producto queda bloqueado — ninguna otra transacción puede modificarlo |
| Estado incierto | El sistema no sabe si debe confirmar o revertir |
| Intervención manual | Un DBA debe decidir y ejecutar manualmente el COMMIT o ROLLBACK |
| Sin resolución automática | PostgreSQL no resuelve esto solo — es el talón de Aquiles del 2PC |

**Resolución manual por el DBA:**

```sql
-- Opción 1: confirmar (si el DBA sabe que el coordinador había terminado bien)
COMMIT PREPARED 'txn_fallo_test';

-- Opción 2: revertir (si no tiene certeza)
-- ROLLBACK PREPARED 'txn_fallo_test';

-- Verificar que desapareció
SELECT gid FROM pg_prepared_xacts;
-- (0 filas) ✅

SELECT stock FROM productos WHERE id = 1;
-- stock: 19 ✅
```

---

## 6. Parte 2 — Juan José: PostgreSQL Replicación, Failover y Experimentos <a name="parte2"></a>

### Ambiente de trabajo

> 📸 **[INSERTAR ACÁ: captura del docker-compose corriendo con los 3 contenedores activos]**

| Componente | Detalle |
|---|---|
| Motor | PostgreSQL 17 |
| Nodos | 1 Primary + 2 Réplicas |
| Herramienta de infraestructura | Docker + docker-compose |
| Latencia simulada | ___ ms entre nodos |

### Infraestructura (`/infra/docker-compose.yaml`)

> **[INSERTAR ACÁ: el contenido del docker-compose.yaml con los 3 nodos y la red configurada]**

```yaml
# Pegar aquí el docker-compose.yaml
```

### Configuración de Replicación

> **[INSERTAR ACÁ: los parámetros configurados en postgresql.conf y pg_hba.conf para la replicación]**

```
# Parámetros relevantes:
# wal_level =
# max_wal_senders =
# synchronous_commit =
# synchronous_standby_names =
```

### Replicación Síncrona vs Asíncrona

> **[INSERTAR ACÁ: explicación de los dos modos y los comandos usados para cambiar entre ellos]**

**Resultados de latencia:**

| Modo | Latencia promedio (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| Asíncrono (synchronous_commit = off) | | | |
| Síncrono (synchronous_commit = on) | | | |

> 📸 **[INSERTAR ACÁ: captura o gráfica de los resultados de latencia]**

**Análisis:** _(Juan José completa acá)_

### Escenario de Failover

> **[INSERTAR ACÁ: pasos ejecutados para bajar el Primary y promover una réplica]**

```bash
# Comandos usados:
```

**Tiempo de failover:** ___ segundos

**¿Cómo se evita el split-brain?** _(Juan José explica acá)_

> 📸 **[INSERTAR ACÁ: captura mostrando el nuevo Primary activo después del failover]**

### Tabla de Experimentos

| Experimento | Métrica | Resultado PostgreSQL |
|---|---|---|
| Latencia escritura síncrona | ms | |
| Latencia escritura asíncrona | ms | |
| Latencia lectura en Primary | ms | |
| Latencia lectura en Réplica | ms | |
| Tiempo de failover manual | segundos | |
| Lag de replicación asíncrona | ms | |
| Impacto con 1 réplica | ms | |
| Impacto con 2 réplicas | ms | |

---

## 7. Parte 3 — Nicolás: NewSQL y Análisis Comparativo <a name="parte3"></a>

### Motor seleccionado

> **[INSERTAR ACÁ: CockroachDB o YugabyteDB — justificar la elección]**

### Ambiente de trabajo

| Componente | Detalle |
|---|---|
| Motor NewSQL | ___ |
| Versión | ___ |
| Nodos | 3 |
| Herramienta | Docker + docker-compose |

> 📸 **[INSERTAR ACÁ: captura del dashboard de admin del clúster NewSQL con los 3 nodos saludables]**

### Infraestructura (`/infra/docker-compose-newsql.yaml`)

```yaml
# Pegar aquí el docker-compose-newsql.yaml
```

### Auto-sharding

> **[INSERTAR ACÁ: explicación de cómo el motor distribuyó los datos automáticamente y comparación con el esfuerzo manual de PostgreSQL]**

```sql
-- Comando para ver la distribución de rangos:
-- SHOW RANGES FROM TABLE transacciones_log;
```

> 📸 **[INSERTAR ACÁ: captura mostrando la distribución de rangos entre los 3 nodos]**

**Comparación de esfuerzo:**

| Aspecto | PostgreSQL (Isabella) | NewSQL (Nicolás) |
|---|---|---|
| Configuración de particiones | Manual — 15+ líneas de SQL | Automático |
| Enrutamiento | Responsabilidad de la app | Transparente |
| Rebalanceo de datos | Manual | Automático |

### Raft y Tolerancia a Fallos

> **[INSERTAR ACÁ: explicación del protocolo Raft, identificación del leaseholder y resultado del failover automático]**

**Tiempo de failover automático:** ___ segundos  
**Tiempo de failover manual PostgreSQL (Juan José):** ___ segundos

> 📸 **[INSERTAR ACÁ: captura mostrando la elección automática de nuevo líder en el dashboard]**

### Transacciones Distribuidas en NewSQL

> **[INSERTAR ACÁ: el mismo escenario de compra multi-nodo ejecutado en NewSQL con BEGIN/COMMIT simple]**

```sql
-- En NewSQL:
BEGIN;
UPDATE productos SET stock = stock - 1 WHERE id = 1;
INSERT INTO pagos (id_pedido, monto, metodo) VALUES (1, 150.00, 'tarjeta');
COMMIT;
-- El motor maneja el consenso distribuido internamente
```

**Comparación:**

| Aspecto | PostgreSQL 2PC | NewSQL |
|---|---|---|
| Líneas de código | ~10 | ~4 |
| Riesgo de bloqueo | Alto (fallo del coordinador) | Ninguno |
| Intervención manual | Necesaria ante fallos | No requerida |
| Latencia | ___ ms | ___ ms |

### Simulación de Partición de Red (CAP)

> **[INSERTAR ACÁ: comandos usados para simular la partición y comportamiento observado]**

```bash
# Herramienta usada: pumba / iptables
```

**Resultado observado:** _(Nicolás completa acá — ¿el sistema prefirió consistencia o disponibilidad?)_

---

## 8. Comparación Final PostgreSQL vs NewSQL <a name="comparacion"></a>

### Tabla PACELC

| Dimensión | PostgreSQL | NewSQL (_____) |
|---|---|---|
| **Particionamiento** | Manual, configurable por rango/hash/list | Automático (auto-sharding por rangos de llave) |
| **Replicación** | Líder-Seguidor, síncrona/asíncrona manual | Raft — consenso automático entre réplicas |
| **Consistencia** | ACID por nodo, 2PC entre nodos (frágil) | ACID distribuido nativo |
| **Disponibilidad** | Failover manual, riesgo de split-brain | Failover automático por Raft |
| **Latencia escritura** | ___ ms (síncrona) / ___ ms (asíncrona) | ___ ms |
| **Latencia lectura** | ___ ms (primary) / ___ ms (réplica) | ___ ms |
| **Transacciones distribuidas** | 2PC manual — riesgo de bloqueo ante fallos | Automático — sin punto único de fallo |
| **Manejo de fallos** | Intervención manual del DBA | Automático vía Raft |
| **Complejidad operativa** | Alta | Baja |
| **Costo infraestructura** | Bajo (open source) | Medio-Alto (licencias o servicio administrado) |
| **Costo administración** | Alto (DBA especializado) | Bajo (servicio administrado) |

### Gráfica comparativa de latencias

> 📸 **[INSERTAR ACÁ: gráfica comparando latencias de escritura y lectura entre PostgreSQL y NewSQL]**

---

## 9. Análisis Crítico <a name="critico"></a>

> **[El equipo completa esta sección en conjunto]**

### ¿En qué escenario real usarías cada motor?

_(Completar con argumentos basados en los experimentos)_

### Casos reales de referencia

_(Incluir al menos 1 caso nacional y 1 internacional donde apliquen estos conceptos — ej: Rappi, Bancolombia, Uber, Netflix)_

### Impacto en costos

| Aspecto | PostgreSQL distribuido | NewSQL administrado en nube |
|---|---|---|
| Licencia | Gratuita | Freemium / pago por uso |
| Infraestructura | EC2/VMs propias | Gestionada por el proveedor |
| DBA requerido | Sí — altamente especializado | Mínimo |
| Costo operativo mensual estimado | ___ | ___ |

### Impacto en administración

_(Reflexión sobre la diferencia entre administrar un clúster PostgreSQL manual vs un servicio NewSQL administrado en nube)_

### Consciencia y transparencia en la vida real

_(¿Qué tan conscientes son los desarrolladores de estos trade-offs en proyectos reales? ¿Cuándo se oculta esta complejidad detrás de servicios administrados?)_

---

## 10. Conclusiones <a name="conclusiones"></a>

### Particionamiento en PostgreSQL

- El particionamiento por **rango** es ideal para datos temporales — permite partition pruning muy efectivo en consultas por fecha.
- El particionamiento por **hash** distribuye la carga uniformemente sin criterio de rango natural.
- **Limitación clave:** PostgreSQL no es distribuido nativamente. El enrutamiento entre nodos físicos debe manejarse en la capa de aplicación o con herramientas externas.

### 2PC en PostgreSQL

- El 2PC garantiza atomicidad en transacciones multi-nodo, pero si el coordinador falla entre PREPARE y COMMIT, los recursos quedan **bloqueados indefinidamente**.
- A nivel industrial esto se mitiga con logs de transacciones persistentes y procesos de recuperación, pero PostgreSQL por sí solo requiere intervención manual del DBA.

### Replicación en PostgreSQL

> _(Juan José completa acá con las conclusiones de sus experimentos)_

### NewSQL vs PostgreSQL

> _(Nicolás completa acá con las conclusiones del análisis comparativo)_

### Reflexión final del equipo

> _(Párrafo conjunto sobre el aprendizaje del proyecto)_

---

## Estructura del Repositorio

```
/
├── README.md
├── /infra
│   ├── docker-compose.yaml          ← 3 nodos PostgreSQL (Juan José)
│   └── docker-compose-newsql.yaml   ← Clúster NewSQL (Nicolás)
└── /scripts
    ├── modelo.sql                   ← Creación de tablas (Isabella)
    ├── generar_datos.py             ← Datos sintéticos (Isabella)
    ├── particionamiento.sql         ← Particiones rango y hash (Isabella)
    └── 2pc.sql                      ← Transacciones distribuidas (Isabella)
```
