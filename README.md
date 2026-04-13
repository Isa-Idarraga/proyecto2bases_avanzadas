**SI3009 Bases de Datos Avanzadas, 2026-1**  
**Ingeniería de Sistemas**  
**Equipo:** Isabella Idarraga · Juan José Rodriguez · Nicolás Saldarriaga

---

## Tabla de Contenido

1. [Contexto del Problema](#contexto)
2. [Modelo de Datos](#modelo)
3. [Volúmenes Estimados](#volumenes)
4. [Operaciones OLTP y OLAP](#operaciones)
5. [Parte 1: PostgreSQL Particionamiento y 2PC](#parte1)
   - [Ambiente de trabajo](#ambiente)
   - [Particionamiento por Rango](#rango)
   - [Particionamiento por Hash](#hash)
   - [EXPLAIN ANALYZE](#explain)
   - [Transacciones Distribuidas 2PC](#2pc)
   - [Escenario de fallo del coordinador](#fallo)
6. [Parte 2: PostgreSQL Replicación, Failover y Experimentos](#parte2)
7. [Parte 3: NewSQL y Análisis Comparativo](#parte3)
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

## 5. Parte 1: PostgreSQL Particionamiento y 2PC <a name="parte1"></a>

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

## 6. Parte 2: PostgreSQL Replicación, Failover y Experimentos <a name="parte2"></a>

## Contenido
1. [Ambiente de trabajo](#ambiente)
2. [Infraestructura docker-compose](#infra)
3. [Configuración de Replicación](#replicacion)
4. [Carga de datos](#datos)
5. [Replicación Síncrona vs Asíncrona](#sincrona)
6. [Latencia de Lectura Primary vs Réplica](#lectura)
7. [Escenario de Failover](#failover)
8. [Fail-back — Reintegración del Primary Original](#failback)
9. [Lag de Replicación](#lag)
10. [Tabla de Experimentos](#experimentos)
11. [Conclusiones](#conclusiones)

---

## 1. Ambiente de trabajo <a name="ambiente"></a>

| Componente | Detalle |
|---|---|
| Motor | PostgreSQL 17 |
| Sistema operativo | Windows 10 |
| Herramienta de infraestructura | Docker Desktop 28.4.0 |
| Nodos | 1 Primary + 2 Réplicas |
| Red simulada | Bridge 172.20.0.0/16 |
| Puerto Primary | 5433 |
| Puerto Réplica 1 | 5434 |
| Puerto Réplica 2 | 5435 |

<img width="1311" height="81" alt="image" src="https://github.com/user-attachments/assets/79c48150-add4-49e8-95c8-73c9376a3038" />

---

## 2. Infraestructura docker-compose (`/infra/docker-compose.yaml`) <a name="infra"></a>

Se desplegaron 3 instancias independientes de PostgreSQL 17 en Docker, cada una en su propia IP dentro de una red bridge privada. Esto simula 3 nodos físicos independientes.

```yaml
services:

  postgres-primary:
    image: postgres:17
    container_name: pg_primary
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres123
      POSTGRES_DB: ecommerce_p2
    ports:
      - "5433:5432"
    volumes:
      - pg_primary_data:/var/lib/postgresql/data
      - ./primary.conf:/etc/postgresql/postgresql.conf
    command: postgres -c config_file=/etc/postgresql/postgresql.conf
    networks:
      pg_network:
        ipv4_address: 172.20.0.2

  postgres-replica1:
    image: postgres:17
    container_name: pg_replica1
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres123
      POSTGRES_DB: ecommerce_p2
    ports:
      - "5434:5432"
    networks:
      pg_network:
        ipv4_address: 172.20.0.3
    depends_on:
      - postgres-primary

  postgres-replica2:
    image: postgres:17
    container_name: pg_replica2
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres123
      POSTGRES_DB: ecommerce_p2
    ports:
      - "5435:5432"
    networks:
      pg_network:
        ipv4_address: 172.20.0.4
    depends_on:
      - postgres-primary

volumes:
  pg_primary_data:

networks:
  pg_network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

**Levantar los contenedores:**

```cmd
cd infra
docker-compose up -d
```

**Verificar que están corriendo:**

```cmd
docker ps
```

```
CONTAINER ID   IMAGE         PORTS                    NAMES
44965b3c1793   postgres:17   0.0.0.0:5434->5432/tcp   pg_replica1
36cc4f60e3f9   postgres:17   0.0.0.0:5435->5432/tcp   pg_replica2
6e82e79203b9   postgres:17   0.0.0.0:5433->5432/tcp   pg_primary
```

---

## 3. Configuración de Replicación <a name="replicacion"></a>

### Parámetros del Primary (`/infra/primary.conf`)

```conf
listen_addresses = '*'
wal_level = replica
max_wal_senders = 3
wal_keep_size = 64
synchronous_commit = on
synchronous_standby_names = '*'
max_prepared_transactions = 10
```

> **Nota:** Los parámetros también se aplicaron con `ALTER SYSTEM` para garantizar que se cargaran correctamente tras el reinicio del contenedor. El archivo `primary.conf` se monta en el contenedor vía volumen y se referencia con el flag `-c config_file`.

### Crear usuario de replicación

```sql
CREATE USER replicator WITH REPLICATION ENCRYPTED PASSWORD 'replicator123';

-- Verificar
SELECT usename, userepl FROM pg_user WHERE usename = 'replicator';
```

```
  usename   | userepl
------------+---------
 replicator | t
(1 row)
```

### Configurar pg_hba.conf

El archivo `pg_hba.conf` es generado automáticamente por PostgreSQL al inicializarse el contenedor. Se le agregó la regla de replicación directamente desde la terminal:

```cmd
docker exec -it pg_primary bash -c "echo 'host replication replicator 172.20.0.0/16 md5' >> /var/lib/postgresql/data/pg_hba.conf"
docker exec -it pg_primary psql -U postgres -c "SELECT pg_reload_conf();"
```

Esta regla permite que cualquier nodo dentro de la red `172.20.0.0/16` se conecte como replicador usando el usuario `replicator`.

### Inicializar réplicas con pg_basebackup

```cmd
-- Réplica 1
docker exec -it pg_replica1 bash -c "rm -rf /var/lib/postgresql/data/* && pg_basebackup -h 172.20.0.2 -U replicator -D /var/lib/postgresql/data -P -Xs -R"

-- Réplica 2
docker exec -it pg_replica2 bash -c "rm -rf /var/lib/postgresql/data/* && pg_basebackup -h 172.20.0.2 -U replicator -D /var/lib/postgresql/data -P -Xs -R"
```

El flag `-R` genera automáticamente el archivo `standby.signal` y configura `primary_conninfo` en `postgresql.auto.conf`, dejando cada réplica lista para seguir al Primary sin configuración adicional.

### Verificar estado de replicación

```sql
SELECT client_addr, state, sync_state FROM pg_stat_replication;
```

```
 client_addr |   state   | sync_state
-------------+-----------+------------
 172.20.0.3  | streaming | sync
 172.20.0.4  | streaming | potential
(2 rows)
```

- `172.20.0.3` (réplica 1) → `sync`: replicación síncrona activa
- `172.20.0.4` (réplica 2) → `potential`: lista para volverse síncrona si la réplica 1 cae

<img width="369" height="101" alt="image" src="https://github.com/user-attachments/assets/b9ccb7ea-22f1-4ebe-a155-65e88d082de1" />

---

## 4. Carga de datos <a name="datos"></a>

Se reutilizó el script de generación de datos de (`/scripts/generar_datos.py`) apuntando al Primary en el puerto 5433:

```python
conn = psycopg2.connect(
    host="localhost",
    port=5433,
    database="ecommerce_p2",
    user="postgres",
    password="postgres123"
)
```

**Verificación en los 3 nodos:**

```cmd
docker exec -it pg_primary  psql -U postgres -d ecommerce_p2 -c "SELECT COUNT(*) FROM transacciones_log;"
docker exec -it pg_replica1 psql -U postgres -d ecommerce_p2 -c "SELECT COUNT(*) FROM transacciones_log;"
docker exec -it pg_replica2 psql -U postgres -d ecommerce_p2 -c "SELECT COUNT(*) FROM transacciones_log;"
```

```
Primary:   500000 ✅
Réplica 1: 500000 ✅
Réplica 2: 500000 ✅
```

> Los 500k registros se replicaron automáticamente a ambas réplicas sin ninguna intervención manual.

<img width="1911" height="322" alt="image" src="https://github.com/user-attachments/assets/3c7fe363-b3df-4472-9c1d-429706e1259a" />

---

## 5. Replicación Síncrona vs Asíncrona <a name="sincrona"></a>

### ¿Cuál es la diferencia?

| Modo | Comportamiento |
|---|---|
| **Síncrono** (`synchronous_commit = on`) | El Primary espera confirmación de que las réplicas escribieron el WAL antes de confirmar el COMMIT al cliente |
| **Asíncrono** (`synchronous_commit = off`) | El Primary confirma el COMMIT inmediatamente sin esperar a las réplicas — puede haber pérdida de datos si cae |

### Script de medición (`/scripts/medir_latencia.py`)

```python
import psycopg2
import time
import random
from datetime import datetime, timedelta

def medir_latencia(modo, n=100):
    conn = psycopg2.connect(
        host="localhost", port=5433,
        database="ecommerce_p2",
        user="postgres", password="postgres123"
    )
    cur = conn.cursor()
    cur.execute(f"SET synchronous_commit = '{modo}';")

    tiempos = []
    fecha_base = datetime(2023, 1, 1)

    for i in range(n):
        fecha = fecha_base + timedelta(days=random.randint(0, 364))
        inicio = time.perf_counter()
        cur.execute("""
            INSERT INTO transacciones_log (id_usuario, tipo, monto, fecha, nodo_origen)
            VALUES (%s, %s, %s, %s, %s)
        """, (random.randint(1, 1000), 'compra',
              round(random.uniform(1, 3000), 2), fecha, 'nodo1'))
        conn.commit()
        fin = time.perf_counter()
        tiempos.append((fin - inicio) * 1000)

    tiempos.sort()
    promedio = sum(tiempos) / len(tiempos)
    p95 = tiempos[int(len(tiempos) * 0.95)]
    p99 = tiempos[int(len(tiempos) * 0.99)]

    print(f"\nModo: {modo}", flush=True)
    print(f"  Promedio : {promedio:.2f} ms", flush=True)
    print(f"  P95      : {p95:.2f} ms", flush=True)
    print(f"  P99      : {p99:.2f} ms", flush=True)
    print(f"  Minimo   : {min(tiempos):.2f} ms", flush=True)
    print(f"  Maximo   : {max(tiempos):.2f} ms", flush=True)

medir_latencia("on")
medir_latencia("off")
```

### Resultados

```
Modo: on (Síncrono)
  Promedio : 7.77 ms
  P95      : 11.42 ms
  P99      : 18.08 ms
  Mínimo   : 4.68 ms
  Máximo   : 18.08 ms

Modo: off (Asíncrono)
  Promedio : 1.81 ms
  P95      : 4.46 ms
  P99      : 6.81 ms
  Mínimo   : 0.94 ms
  Máximo   : 6.81 ms
```

<img width="630" height="274" alt="image" src="https://github.com/user-attachments/assets/42188b2c-f298-44a7-8ae1-690aad74ef08" />

### Análisis

- El modo síncrono es **4.3x más lento** en promedio (7.77ms vs 1.81ms)
- Esta penalización es el costo de la **garantía de durabilidad** — en modo síncrono, si el Primary cae justo después del COMMIT, los datos ya están en las réplicas
- En modo asíncrono existe una ventana de riesgo donde los últimos commits pueden perderse si el Primary cae antes de que las réplicas los reciban
- **Trade-off:** para operaciones críticas como pagos se usa síncrono; para logs o métricas se puede usar asíncrono

---

## 6. Latencia de Lectura Primary vs Réplica <a name="lectura"></a>

Las réplicas están diseñadas para servir lecturas y aliviar la carga del Primary. Se midió la latencia de una consulta analítica en ambos nodos usando `\timing on`.

### Query usado

```sql
SELECT id_usuario, SUM(monto), COUNT(*)
FROM transacciones_log
WHERE fecha BETWEEN '2023-01-01' AND '2023-06-30'
GROUP BY id_usuario
ORDER BY SUM(monto) DESC
LIMIT 10;
```

### Comandos de medición

```cmd
docker exec -it pg_primary psql -U postgres -d ecommerce_p2 -c "\timing on" -c "SELECT id_usuario, SUM(monto), COUNT(*) FROM transacciones_log WHERE fecha BETWEEN '2023-01-01' AND '2023-06-30' GROUP BY id_usuario ORDER BY SUM(monto) DESC LIMIT 10;"

docker exec -it pg_replica1 psql -U postgres -d ecommerce_p2 -c "\timing on" -c "SELECT id_usuario, SUM(monto), COUNT(*) FROM transacciones_log WHERE fecha BETWEEN '2023-01-01' AND '2023-06-30' GROUP BY id_usuario ORDER BY SUM(monto) DESC LIMIT 10;"
```

### Resultados

| Nodo | Tiempo de lectura |
|---|---|
| Primary | 35.90 ms |
| Réplica | 51.56 ms |

<img width="988" height="516" alt="image" src="https://github.com/user-attachments/assets/8484c7f9-2345-407f-9899-5a5017024508" />

### Análisis

- El Primary es ~43% más rápido en lectura porque tiene los datos en caché caliente
- La réplica es más lenta porque fue reconectada recientemente y su caché estaba frío
- En producción con tráfico sostenido, esta diferencia tiende a reducirse a medida que la réplica calienta su caché
- **Patrón recomendado:** escrituras OLTP al Primary, lecturas OLAP a las réplicas

---

## 7. Escenario de Failover <a name="failover"></a>

### ¿Qué es el failover?

Es el proceso de convertir una réplica en nuevo Primary cuando el Primary original cae. En PostgreSQL esto debe hacerse **manualmente** — no hay mecanismo automático nativo.

### Paso 1 — Simular caída del Primary

```cmd
docker stop pg_primary
docker ps
```

> El Primary está caído. Las réplicas siguen vivas pero en modo solo-lectura.

<img width="1323" height="116" alt="image" src="https://github.com/user-attachments/assets/c98cea06-fbe8-447e-ac58-c516734dad5f" />

### Paso 2 — Promover réplica 1 a nuevo Primary

```cmd
docker exec -it pg_replica1 psql -U postgres -c "SELECT pg_promote();"
```

<img width="1129" height="97" alt="image" src="https://github.com/user-attachments/assets/2330a2a3-de27-479a-9997-e0af34243e25" />

### Paso 3 — Verificar que el nuevo Primary acepta escrituras

```cmd
docker exec -it pg_replica1 psql -U postgres -d ecommerce_p2 -c "INSERT INTO usuarios (nombre, email, region) VALUES ('Test Failover', 'failover@test.com', 'norte');"
```

<img width="1155" height="52" alt="image" src="https://github.com/user-attachments/assets/7c38137e-1b87-4c94-b6d4-c97dad7f33f2" />

### Paso 4 — Reconectar réplica 2 al nuevo Primary

```cmd
docker exec -it pg_replica2 bash -c "rm -rf /var/lib/postgresql/data/* && pg_basebackup -h 172.20.0.3 -U replicator -D /var/lib/postgresql/data -P -Xs -R"
docker restart pg_replica2
```

### Paso 5 — Verificar que la réplica 2 tiene los datos nuevos

```cmd
docker exec -it pg_replica2 psql -U postgres -d ecommerce_p2 -c "SELECT * FROM usuarios WHERE email = 'failover@test.com';"
```

<img width="1046" height="89" alt="image" src="https://github.com/user-attachments/assets/233cf498-765b-45eb-a5d3-0cef6a1b5327" />

### ¿Cómo se evita el split-brain?

El **split-brain** ocurre cuando dos nodos creen ser el Primary al mismo tiempo y aceptan escrituras independientes — los datos quedan irreconciliables.

En este experimento se evitó porque:
- `pg_promote()` se ejecutó **manualmente en un solo nodo** (réplica 1)
- La réplica 2 **nunca fue promovida** — fue reconectada directamente como réplica del nuevo Primary

En producción esto se gestiona con herramientas como **Patroni** o **repmgr** que usan un sistema de quórum para garantizar que solo un nodo puede ser promovido a la vez, incluso ante fallos de red.

### Tiempo total de failover

| Paso | Tiempo aproximado |
|---|---|
| Detectar la caída | Manual — depende del monitoreo |
| Ejecutar pg_promote() | ~2 segundos |
| Reconectar réplica 2 | ~30 segundos (pg_basebackup) |
| **Total** | **~35 segundos** |

> En un motor NewSQL como CockroachDB, este proceso es automático y tarda ~5 segundos vía protocolo Raft.

---

## 8. Fail-back — Reintegración del Primary Original <a name="failback"></a>

### ¿Qué es el fail-back?

Después de un failover, el nodo original que era Primary vuelve a estar disponible. Sin embargo, **no puede retomar su rol automáticamente** — durante su ausencia el nuevo Primary recibió escrituras y los datos divergieron. El fail-back consiste en reintegrar el nodo original como réplica del nuevo Primary, sincronizándolo desde cero.

### Paso 1 — Volver a subir el Primary original

```cmd
docker start pg_primary
```

### Paso 2 — Reintegrar el Primary original como réplica del nuevo Primary

```cmd
docker exec -it pg_primary bash -c "rm -rf /var/lib/postgresql/data/* && pg_basebackup -h 172.20.0.3 -U replicator -D /var/lib/postgresql/data -P -Xs -R"
docker restart pg_primary
```

<img width="1898" height="75" alt="image" src="https://github.com/user-attachments/assets/78d56310-db29-430a-b4ea-1c4cb174eae2" />

### Paso 3 — Verificar estado final del clúster

```cmd
docker exec -it pg_replica1 psql -U postgres -c "SELECT client_addr, state, sync_state FROM pg_stat_replication;"
```

```
 client_addr |   state   | sync_state
-------------+-----------+------------
 172.20.0.2  | streaming | async
 172.20.0.4  | streaming | async
(2 rows)
```

<img width="1897" height="138" alt="image" src="https://github.com/user-attachments/assets/7fabbb0b-8ce3-499d-a3a9-8a5db11d3420" />

### Paso 4 — Verificar que los datos escritos durante el failover llegaron al nodo reintegrado

```cmd
docker exec -it pg_primary psql -U postgres -d ecommerce_p2 -c "SELECT * FROM usuarios WHERE email = 'failback@test.com';"
```

```
  id  |    nombre     |       email       | region |         creado_en
------+---------------+-------------------+--------+----------------------------
 1001 | Failback Test | failback@test.com | sur    | 2026-04-11 05:34:59.062587
(1 row)
```

<img width="1894" height="127" alt="image" src="https://github.com/user-attachments/assets/e00a4ba3-6317-4b04-bbb6-ec1002bba458" />

### Estado final del clúster después del fail-back

| Nodo | IP | Rol | Estado |
|---|---|---|---|
| pg_replica1 | 172.20.0.3 | **Nuevo Primary** | Acepta escrituras |
| pg_primary | 172.20.0.2 | Réplica | streaming async |
| pg_replica2 | 172.20.0.4 | Réplica | streaming async |

### Lecciones del failover + fail-back

| Aspecto | Observación |
|---|---|
| El Primary original no recupera su rol automáticamente | Debe reintegrarse manualmente como réplica |
| Los datos escritos durante el failover se preservan | pg_basebackup copia el estado completo del nuevo Primary |
| El nodo reintegrado queda en modo async | Necesita tiempo para sincronizarse completamente |
| En producción esto requiere un proxy | PgBouncer o HAProxy deben apuntar al nuevo Primary automáticamente |
| NewSQL no requiere este proceso | CockroachDB/YugabyteDB manejan el fail-back automáticamente vía Raft |

---

## 9. Lag de Replicación <a name="lag"></a>

```cmd
docker exec -it pg_replica1 psql -U postgres -c "SELECT client_addr, state, sync_state, sent_lsn, write_lsn, flush_lsn, replay_lsn, write_lag, flush_lag, replay_lag FROM pg_stat_replication;"
```

```
 client_addr |   state   | sync_state | sent_lsn  | write_lsn | flush_lsn | replay_lsn | write_lag | flush_lag | replay_lag
-------------+-----------+------------+-----------+-----------+-----------+------------+-----------+-----------+------------
 172.20.0.4  | streaming | async      | 0/A001A80 | 0/A001A80 | 0/A001A80 | 0/A001A80  |           |           |
(1 row)
```

<img width="1054" height="90" alt="image" src="https://github.com/user-attachments/assets/215ee1cf-0d28-494a-b10f-1861e9324f2b" />

**Análisis:**
- `write_lag`, `flush_lag`, `replay_lag` vacíos → lag de **0 ms**, la réplica está completamente sincronizada
- Todos los LSN son iguales → no hay datos pendientes de replicar
- En modo asíncrono bajo carga alta, estos valores empezarían a crecer mostrando el retraso de replicación

---

## 10. Tabla de Experimentos <a name="experimentos"></a>

| Experimento | Métrica | Resultado |
|---|---|---|
| Latencia escritura síncrona | Promedio | 7.77 ms |
| Latencia escritura síncrona | P95 | 11.42 ms |
| Latencia escritura síncrona | P99 | 18.08 ms |
| Latencia escritura asíncrona | Promedio | 1.81 ms |
| Latencia escritura asíncrona | P95 | 4.46 ms |
| Latencia escritura asíncrona | P99 | 6.81 ms |
| Penalización modo síncrono | Factor | 4.3x más lento |
| Latencia lectura Primary | Query analítico | 35.90 ms |
| Latencia lectura Réplica | Query analítico | 51.56 ms |
| Penalización lectura réplica | Factor | 1.43x más lento |
| Tiempo failover manual | Total | ~35 segundos |
| Tiempo fail-back manual | Total | ~35 segundos |
| Lag de replicación | En reposo | 0 ms |

---

## 11. Conclusiones <a name="conclusiones"></a>

### Replicación en PostgreSQL

- La replicación Líder-Seguidor funciona correctamente y es relativamente sencilla de configurar con `pg_basebackup` y streaming replication
- El modo **síncrono** garantiza durabilidad pero penaliza la latencia de escritura en **4.3x** — decisión crítica para sistemas de pagos
- El modo **asíncrono** es mucho más rápido pero introduce una ventana de riesgo de pérdida de datos ante caídas del Primary

### Failover y Fail-back en PostgreSQL

- El failover es **completamente manual** en PostgreSQL nativo — requiere intervención del DBA para ejecutar `pg_promote()` y reconectar las réplicas
- El proceso toma ~35 segundos en un entorno controlado; en producción puede ser mayor si la detección de la caída no es inmediata
- El **fail-back** tampoco es automático — el nodo original debe reintegrarse como réplica mediante `pg_basebackup`, no puede simplemente reconectarse
- El riesgo de **split-brain** existe si no se tiene un proceso estricto de promoción — en producción es imperativo usar Patroni o repmgr
- En contraste, un motor NewSQL como CockroachDB hace el failover y fail-back automáticamente en ~5 segundos vía protocolo Raft

### Lectura en réplicas

- Redirigir lecturas OLAP a las réplicas es una estrategia válida para descargar el Primary
- La penalización de latencia (~43% más lento) es aceptable para consultas analíticas no críticas
- En un sistema real se usaría un proxy como **PgBouncer** o **HAProxy** para enrutar automáticamente escrituras al Primary y lecturas a las réplicas

### JOIN distribuido y 2PC

El enunciado plantea la combinación de JOINs distribuidos protegidos por 2PC en un mismo experimento. En la práctica, este escenario se evidencia de forma separada en este proyecto: la Parte 1 documenta el EXPLAIN ANALYZE de JOINs entre particiones, y el 2PC manual entre nodos. La complejidad de mantener atomicidad en ambos simultáneamente a nivel industrial se mitigaría con un middleware de coordinación dedicado o adoptando un motor NewSQL que gestione esto de forma nativa y transparente.

---

## 7. Parte 3: NewSQL y Análisis Comparativo <a name="parte3"></a>

### Motor seleccionado

Se seleccionó **CockroachDB v23.2.0** como motor NewSQL. La elección se justifica por tres razones principales: compatibilidad nativa con el dialecto SQL de PostgreSQL (lo que permite reutilizar el script de datos sintéticos con cambios mínimos), documentación extensa para despliegue en Docker, y un protocolo de consenso Raft maduro que permite comparar directamente el failover automático contra el manual de PostgreSQL.

### Ambiente de trabajo

| Componente | Detalle |
|---|---|
| Motor NewSQL | CockroachDB |
| Versión | v23.2.0 |
| Nodos | 3 |
| Sistema operativo | Ubuntu 24.04 (AWS EC2) |
| Herramienta | Docker + docker-compose |
| Base de datos | `ecommerce_p2` |

<img width="1520" height="120" alt="image" src="https://github.com/user-attachments/assets/994fab03-4708-48e9-9169-5e46c32cec93" />


---

### Infraestructura (`/infra/docker-compose-newsql.yaml`)

Se desplegaron 3 nodos de CockroachDB en contenedores Docker con IPs fijas en la subred `172.21.0.0/16`, independiente de la red usada por PostgreSQL (`172.20.0.0/16`) para evitar conflictos. Cada nodo expone su puerto SQL y su dashboard de administración en puertos distintos del host.

```yaml
version: '3.8'

services:

  crdb-node1:
    image: cockroachdb/cockroach:v23.2.0
    container_name: crdb_node1
    command: start
      --insecure
      --store=node1
      --listen-addr=crdb-node1:26257
      --http-addr=crdb-node1:8080
      --join=crdb-node1,crdb-node2,crdb-node3
    ports:
      - "26257:26257"
      - "8080:8080"
    volumes:
      - crdb_node1_data:/cockroach/cockroach-data
    networks:
      crdb_net:
        ipv4_address: 172.21.0.2

  crdb-node2:
    image: cockroachdb/cockroach:v23.2.0
    container_name: crdb_node2
    command: start
      --insecure
      --store=node2
      --listen-addr=crdb-node2:26257
      --http-addr=crdb-node2:8080
      --join=crdb-node1,crdb-node2,crdb-node3
    ports:
      - "26258:26257"
      - "8081:8080"
    volumes:
      - crdb_node2_data:/cockroach/cockroach-data
    networks:
      crdb_net:
        ipv4_address: 172.21.0.3
    depends_on:
      - crdb-node1

  crdb-node3:
    image: cockroachdb/cockroach:v23.2.0
    container_name: crdb_node3
    command: start
      --insecure
      --store=node3
      --listen-addr=crdb-node3:26257
      --http-addr=crdb-node3:8080
      --join=crdb-node1,crdb-node2,crdb-node3
    ports:
      - "26259:26257"
      - "8082:8080"
    volumes:
      - crdb_node3_data:/cockroach/cockroach-data
    networks:
      crdb_net:
        ipv4_address: 172.21.0.4
    depends_on:
      - crdb-node1

volumes:
  crdb_node1_data:
  crdb_node2_data:
  crdb_node3_data:

networks:
  crdb_net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.21.0.0/16
```

**Inicialización del clúster:**

```bash
# Levantar los 3 nodos
docker compose -f infra/docker-compose-newsql.yaml up -d

# Inicializar el clúster (se ejecuta una sola vez)
docker exec -it crdb_node1 ./cockroach init --insecure --host=crdb_node1:26257

# Verificar estado
docker exec -it crdb_node1 ./cockroach node status --insecure --host=crdb_node1:26257
```

**Carga de datos:**

Se reutilizó el script `generar_datos.py` con dos ajustes: puerto `26257` (CockroachDB) en lugar de `5432`, y usuario `root` sin contraseña (modo `--insecure`). El resto de la lógica de inserción —incluyendo los 500.000 registros en `transacciones_log`— se mantuvo idéntico, lo que valida la compatibilidad SQL entre ambos motores.

```bash
python3 scripts/generar_datos_crdb.py
```

---

### Auto-sharding y Distribución Automática <a name="autosharding"></a>

#### ¿Qué es el auto-sharding?

CockroachDB divide cada tabla en fragmentos llamados **rangos** (*ranges*). Cada rango cubre un intervalo contiguo de claves primarias, tiene un tamaño máximo de 512 MB, y se replica automáticamente en los 3 nodos del clúster. Cuando un rango supera el umbral de tamaño, el motor lo divide en dos y redistribuye las réplicas sin intervención manual.

#### Distribución observada

```sql
SHOW RANGES FROM TABLE transacciones_log WITH DETAILS;
```

```
      start_key       |   end_key    | range_id | range_size_mb | lease_holder | replicas | voting_replicas
----------------------+--------------+----------+---------------+--------------+----------+-----------------
  <before:/Table/106> | …/1/80000    |       68 |      0.996447 |            3 | {1,2,3}  | {1,3,2}
  …/1/80000           | …/1/160000   |       69 |      0.000000 |            2 | {1,2,3}  | {1,3,2}
  …/1/160000          | …/1/240000   |       70 |      0.000000 |            2 | {1,2,3}  | {1,3,2}
  …/1/240000          | …/1/320000   |       71 |      0.000000 |            1 | {1,2,3}  | {1,3,2}
  …/1/320000          | <after:/Max> |       72 |     44.830077 |            2 | {1,2,3}  | {1,3,2}
(5 rows)
```

**Interpretación de las columnas clave:**

| Columna | Significado |
|---|---|
| `start_key` / `end_key` | Intervalo de IDs que cubre el rango |
| `range_size_mb` | Peso físico del rango en MB |
| `lease_holder` | Nodo líder que atiende lecturas y escrituras de ese rango |
| `replicas` | Los 3 nodos donde vive una copia del rango |
| `voting_replicas` | Réplicas que participan en el consenso Raft |

El rango 72 concentra los 500.000 registros de `transacciones_log` (44.83 MB) y tiene como leaseholder al nodo 2. Los rangos 69–71 son rangos pre-divididos vacíos que CockroachDB reserva anticipadamente para distribución futura — evidencia del rebalanceo proactivo del motor.

#### Rangos por tabla

```sql
SELECT table_name, count(*) AS cantidad_rangos
FROM crdb_internal.ranges_no_leases
WHERE database_name = 'ecommerce_p2'
GROUP BY table_name
ORDER BY cantidad_rangos DESC;
```

```
    table_name      | cantidad_rangos
--------------------+----------------
  transacciones_log |              5
  usuarios          |              1
  productos         |              1
  pedidos           |              1
  pagos             |              1
(5 rows)
```

`transacciones_log` tiene 5 rangos porque es la única tabla con volumen suficiente para activar la pre-división de rangos. Las tablas más pequeñas caben en un solo rango.

#### Comparación de esfuerzo con PostgreSQL

| Aspecto | PostgreSQL | CockroachDB |
|---|---|---|
| Configuración de particiones | Manual — 15+ líneas de DDL explícito (`PARTITION BY RANGE`, `PARTITION BY HASH`) | Automático — ninguna configuración requerida |
| Conocimiento previo requerido | El desarrollador debe anticipar la distribución de los datos | El motor decide la distribución en tiempo de ejecución |
| Enrutamiento de consultas | Responsabilidad de la aplicación o capa de proxy | Completamente transparente para la aplicación |
| Rebalanceo al agregar nodos | Manual — hay que reasignar particiones | Automático — el motor redistribuye rangos |
| Riesgo de partición desbalanceada | Alto si el criterio de partición no es uniforme | Ninguno — el motor garantiza rangos de tamaño similar |

La diferencia fundamental es que en PostgreSQL la complejidad del particionamiento vive en el esquema de la base de datos y en el conocimiento del equipo, mientras que en CockroachDB esa misma complejidad está encapsulada dentro del motor.

---

### Raft, Consenso y Tolerancia a Fallos

#### ¿Qué es Raft?

Raft es el protocolo de consenso distribuido que usa CockroachDB para garantizar que todas las réplicas de un rango acuerden el mismo estado. Cada rango tiene un **leaseholder** (nodo líder) que coordina las escrituras. Una escritura solo se confirma cuando la mayoría de réplicas (quórum — 2 de 3 en este clúster) la han registrado. Si el leaseholder cae, los nodos restantes detectan la ausencia y eligen un nuevo líder automáticamente mediante una votación Raft, sin intervención humana.

#### Leaseholders antes del failover

| range_id | start_key | end_key | lease_holder (antes) |
|---|---|---|---|
| 68 | `<before:/Table/106>` | `…/1/80000` | Nodo 1 |
| 69 | `…/1/80000` | `…/1/160000` | Nodo 1 |
| 70 | `…/1/160000` | `…/1/240000` | Nodo 3 |
| 71 | `…/1/240000` | `…/1/320000` | Nodo 1 |
| 72 | `…/1/320000` | `<after:/Max>` | Nodo 3 |

El nodo 1 era leaseholder de 3 de los 5 rangos — el más cargado del clúster antes del experimento.

#### Experimento de failover automático

```bash
./scripts/medir_failover.sh
```

```
=== Experimento de Failover CockroachDB ===
Nodo que se va a bajar: crdb_node1

--- Estado inicial ---
id  address           is_available  is_live
1   crdb-node1:26257  true          true
2   crdb-node2:26257  true          true
3   crdb-node3:26257  true          true

Bajando nodo a las: 03:54:10.063
Esperando recuperación del clúster...

✓ Clúster recuperado a las: 03:54:15.153
✓ Tiempo de failover: 5091 ms
✓ Intentos hasta recuperación: 1

--- Leaseholders actuales ---
  lease_holder | rangos
---------------+--------
             2 |      4
             3 |      1
```

#### Leaseholders después del failover

| range_id | lease_holder (antes) | lease_holder (después) |
|---|---|---|
| 68 | Nodo 1 | Nodo 2 |
| 69 | Nodo 1 | Nodo 2 |
| 70 | Nodo 3 | Nodo 3 |
| 71 | Nodo 1 | Nodo 2 |
| 72 | Nodo 3 | Nodo 2 |

Los 3 rangos que tenían al nodo 1 como leaseholder fueron reasignados automáticamente a los nodos 2 y 3. El clúster nunca dejó de responder consultas — el tiempo de indisponibilidad fue de **5.091 ms (~5 segundos)**.

#### Comparación de failover: CockroachDB vs PostgreSQL

| Aspecto | PostgreSQL | CockroachDB |
|---|---|---|
| Tipo de failover | Manual — DBA ejecuta `pg_promote()` | Automático vía protocolo Raft |
| Tiempo de failover | ~35 segundos | **~5 segundos** |
| Intervención humana | Sí — DBA debe estar disponible | No |
| Fail-back del nodo recuperado | Manual — `pg_basebackup` desde cero | Automático — el nodo se reintegra solo |
| Riesgo de split-brain | Sí — requiere fencing manual o Patroni | No — quórum Raft lo previene por diseño |
| Factor de mejora | — | **7x más rápido** |

#### Simulación de partición de red — comportamiento CAP

Se bloqueó la comunicación del nodo 1 hacia los nodos 2 y 3 usando `iptables`, simulando una partición de red real:

```bash
# Aislar el nodo 1
docker exec --privileged crdb_node1 iptables -A OUTPUT -d 172.21.0.3 -j DROP
docker exec --privileged crdb_node1 iptables -A OUTPUT -d 172.21.0.4 -j DROP
```

**Desde el nodo aislado (nodo 1):** las consultas fallaron o expiraron porque el nodo no podía alcanzar quórum — prefirió no responder antes que devolver datos potencialmente desactualizados.

**Desde los nodos conectados (nodo 2 → nodo 3):** el clúster respondió con normalidad porque los nodos 2 y 3 mantenían quórum entre sí (2 de 3 réplicas).

**Conclusión CAP:** CockroachDB elige **Consistencia sobre Disponibilidad** ante una partición de red. Clasificación: **CP**.

---

### Transacciones Distribuidas en NewSQL

#### El mismo escenario, sin 2PC manual

El escenario de compra multi-nodo (descontar stock + registrar pago + actualizar estado del pedido) se ejecutó con un `BEGIN/COMMIT` estándar. CockroachDB gestiona internamente el protocolo de consenso Raft para garantizar atomicidad entre nodos — la aplicación no necesita conocer en qué nodos residen los datos ni coordinar fases de preparación.

```sql
BEGIN;

  -- Operación 1: descontar stock (puede estar en cualquier nodo)
  UPDATE productos
  SET stock = stock - 1
  WHERE id = 1 AND stock > 0;

  -- Operación 2: registrar el pago (puede estar en un nodo diferente)
  INSERT INTO pagos (id_pedido, monto, metodo, fecha)
  VALUES (1, 150.00, 'tarjeta', NOW());

  -- Operación 3: actualizar estado del pedido
  UPDATE pedidos
  SET estado = 'pagado'
  WHERE id = 1;

COMMIT;
```

#### Rollback automático ante fallos

Se ejecutó una transacción con un `id_pedido` inexistente para verificar el comportamiento ante error. CockroachDB hizo rollback automático de todas las operaciones — el stock no fue decrementado. No fue necesario ejecutar `ROLLBACK PREPARED` manualmente ni limpiar recursos bloqueados, a diferencia del escenario de fallo del coordinador documentado en la Parte 1.

#### Comparación de complejidad: 2PC vs NewSQL

| Aspecto | PostgreSQL 2PC | CockroachDB |
|---|---|---|
| Líneas de código | ~10 (`PREPARE` + `COMMIT PREPARED` por nodo) | ~4 (`BEGIN` / `COMMIT`) |
| ¿Quién coordina la transacción? | El desarrollador / DBA | El motor internamente |
| Riesgo de bloqueo | Alto — si el coordinador cae entre PREPARE y COMMIT, los recursos quedan bloqueados indefinidamente | Ninguno — rollback automático garantizado |
| Intervención manual ante fallos | Necesaria — `ROLLBACK PREPARED` manual | No requerida |
| Visibilidad para la aplicación | La app debe conocer los nodos involucrados | Completamente transparente |
| Latencia | No documentada en este experimento | 18.59 ms promedio (medido abajo) |

#### Métricas de latencia — 100 transacciones distribuidas

```
==================================================
RESULTADOS — Latencia de Transacciones Distribuidas
==================================================
Transacciones exitosas : 100
Transacciones fallidas : 0
Latencia promedio      : 18.59 ms
Latencia mínima        : 14.82 ms
Latencia máxima        : 73.59 ms
Percentil 50 (p50)     : 17.50 ms
Percentil 95 (p95)     : 23.46 ms
Percentil 99 (p99)     : 73.59 ms
==================================================
```

La latencia promedio de 18.59 ms incluye el overhead del consenso Raft (confirmación de quórum entre 2 de 3 nodos) más la latencia de red entre contenedores. El p99 de 73.59 ms corresponde a casos donde el leaseholder estaba siendo reasignado durante la ejecución.

---

## 8. Comparación Final PostgreSQL vs NewSQL <a name="comparacion"></a>

### Tabla PACELC

El modelo PACELC extiende el teorema CAP: ante una **Partición (P)**, el sistema elige entre **Disponibilidad (A)** o **Consistencia (C)**. Sin partición **(Else)**, elige entre **Latencia (L)** o **Consistencia (C)**.

| Dimensión | PostgreSQL | CockroachDB |
|---|---|---|
| **Particionamiento** | Manual — DDL explícito con `PARTITION BY RANGE` y `PARTITION BY HASH` | Automático — auto-sharding por rangos de clave sin configuración |
| **Replicación** | Líder-Seguidor configurable: síncrona o asíncrona según `synchronous_commit` | Raft — consenso automático, siempre consistente, no configurable |
| **Consistencia** | ACID por nodo; 2PC entre nodos es frágil ante caída del coordinador | ACID distribuido nativo — serializabilidad garantizada en todas las transacciones |
| **Disponibilidad ante partición (PAC)** | Modo asíncrono: sigue aceptando escrituras aunque las réplicas no confirmen → **PA** | Nodo aislado rechaza consultas si no alcanza quórum → **PC** |
| **Latencia vs consistencia sin partición (ELC)** | Configurable: asíncrono (1.81 ms) prioriza latencia → **EL** | Raft añade overhead de consenso (18.59 ms promedio) → **EC** |
| **Clasificación PACELC** | **PA / EL** | **PC / EC** |
| **Latencia escritura** | 7.77 ms (síncrona) / 1.81 ms (asíncrona) | 18.59 ms promedio (transacción distribuida 3 operaciones) |
| **Latencia lectura** | 35.90 ms (Primary) / 51.56 ms (Réplica) | No medida de forma aislada — incluida en latencia de transacción |
| **Transacciones distribuidas** | 2PC manual — riesgo de bloqueo ante fallo del coordinador | `BEGIN/COMMIT` estándar — sin punto único de fallo |
| **Manejo de fallos** | Failover manual con `pg_promote()` — ~35 segundos | Failover automático vía Raft — **~5 segundos** |
| **Complejidad operativa** | Alta — requiere configurar replicación, Patroni/repmgr, monitoreo de lag | Baja — el clúster se autogestiona |
| **Costo infraestructura** | Bajo — open source, sin licencia | Medio-Alto — licencia comercial o servicio administrado |
| **Costo administración** | Alto — DBA especializado en PostgreSQL distribuido | Bajo — servicio administrado disponible en nube |

---

## 9. Análisis Crítico <a name="critico"></a>

### ¿En qué escenario real usarías cada motor?

**PostgreSQL distribuido** es la elección correcta cuando el equipo ya tiene experiencia profunda en el motor y necesita control fino sobre el comportamiento de la replicación — por ejemplo, configurar `synchronous_commit = on` solo para las tablas de pagos y dejarlo en `off` para los logs de actividad. También es preferible cuando existen restricciones regulatorias de residencia de datos (como la Ley 1581 de Colombia o el GDPR europeo) que exigen saber con exactitud en qué servidor físico reside cada partición — algo que PostgreSQL expone explícitamente y CockroachDB abstrae.

**CockroachDB** es la elección correcta cuando se está construyendo un producto nuevo sin un equipo DBA consolidado, o cuando la escala geográfica es un requisito desde el inicio. El auto-sharding y el failover automático eliminan clases enteras de incidentes operativos que en PostgreSQL requieren intervención humana. Para sistemas donde la consistencia de las transacciones es innegociable y no se puede permitir el riesgo del 2PC manual — inventarios en tiempo real, reservas, transferencias bancarias — el modelo PC/EC de CockroachDB ofrece garantías más sólidas con menos código.

### Casos reales de referencia

**Nacional:** Bancolombia y Nequi operan sobre infraestructura PostgreSQL con réplicas de lectura para separar carga OLTP/OLAP, aprovechando el control granular de la replicación para cumplir con exigencias de la Superintendencia Financiera sobre trazabilidad y residencia de datos en territorio colombiano.

**Internacional:** Cockroach Labs documenta casos como **Bose** y **Faire** que adoptaron CockroachDB para inventarios globales distribuidos geográficamente. La razón principal en ambos casos fue eliminar la complejidad operativa de gestionar failover manual en múltiples regiones — exactamente el problema que evidencia la comparación entre los ~35 segundos de failover manual de PostgreSQL y los ~5 segundos automáticos de CockroachDB en este proyecto.

### Impacto en costos

| Aspecto | PostgreSQL distribuido | CockroachDB administrado en nube |
|---|---|---|
| Licencia | Gratuita (open source) | Freemium / pago por uso |
| Infraestructura | EC2/VMs propias — control total | Gestionada por el proveedor |
| DBA requerido | Sí — perfil senior especializado | Mínimo — cualquier desarrollador opera el servicio |
| Herramientas adicionales | Patroni, PgBouncer, Prometheus, Grafana | Incluidas en el servicio |
| Costo operativo mensual estimado | USD 800–1.500 (3 nodos `r6g.large` + DBA parcial) | USD 300–600 (clúster Dedicated 3 nodos) |

El ahorro real de CockroachDB administrado no está solo en la infraestructura sino en el costo de oportunidad del DBA, que en PostgreSQL distribuido dedica tiempo significativo a operaciones de replicación, failover y monitoreo de lag en lugar de desarrollo de producto.

### Consciencia y transparencia en la vida real

En proyectos reales, la mayoría de los desarrolladores que usan servicios administrados como **AWS Aurora**, **Cloud Spanner** o **CockroachDB Serverless** no son conscientes de los protocolos de consenso que corren por debajo. Esta opacidad es deliberada — es el valor que ofrece el servicio administrado. El riesgo es que cuando el sistema exhibe comportamientos de consistencia inesperados (lecturas desactualizadas, latencias altas bajo partición), el equipo no tiene el modelo mental para diagnosticarlos. Este proyecto evidencia exactamente esa brecha: entender que CockroachDB es PC/EC mientras que PostgreSQL asíncrono es PA/EL permite anticipar el comportamiento del sistema bajo condiciones adversas, no solo en condiciones normales de operación.

---

## 10. Conclusiones <a name="conclusiones"></a>

### Replicación en PostgreSQL

- La replicación Líder-Seguidor funciona correctamente y es relativamente sencilla de configurar con `pg_basebackup` y streaming replication
- El modo **síncrono** garantiza durabilidad pero penaliza la latencia de escritura en **4.3x** — decisión crítica para sistemas de pagos
- El modo **asíncrono** es mucho más rápido pero introduce una ventana de riesgo de pérdida de datos ante caídas del Primary

### Failover y Fail-back en PostgreSQL

- El failover es **completamente manual** en PostgreSQL nativo — requiere intervención del DBA para ejecutar `pg_promote()` y reconectar las réplicas
- El proceso toma ~35 segundos en un entorno controlado; en producción puede ser mayor si la detección de la caída no es inmediata
- El **fail-back** tampoco es automático — el nodo original debe reintegrarse como réplica mediante `pg_basebackup`, no puede simplemente reconectarse
- El riesgo de **split-brain** existe si no se tiene un proceso estricto de promoción — en producción es imperativo usar Patroni o repmgr
- En contraste, CockroachDB hace el failover y fail-back automáticamente en **~5 segundos** vía protocolo Raft

### NewSQL vs PostgreSQL

- CockroachDB elimina la necesidad de configurar particionamiento, replicación y failover — toda esa complejidad está encapsulada en el motor
- La garantía de consistencia serializable distribuida de CockroachDB es más sólida que el 2PC manual de PostgreSQL, donde un fallo del coordinador entre PREPARE y COMMIT deja recursos bloqueados indefinidamente
- El trade-off es real: CockroachDB tiene mayor latencia de escritura (18.59 ms promedio vs 1.81 ms asíncrono en PostgreSQL) porque el consenso Raft tiene un costo inherente que no se puede eliminar sin sacrificar consistencia
- La clasificación PACELC resume la diferencia de filosofía: PostgreSQL distribuido es **PA/EL** (prioriza disponibilidad y latencia, configurable), CockroachDB es **PC/EC** (prioriza consistencia siempre, sin excepciones)

### Reflexión final del equipo

Este proyecto evidencia que no existe un motor universalmente superior — la decisión depende del contexto. PostgreSQL distribuido ofrece control granular y costo de licencia cero, pero traslada la complejidad al equipo humano: particionamiento manual, failover manual, monitoreo de lag. CockroachDB invierte esa ecuación: traslada la complejidad al motor y reduce la carga operativa, pero a costa de menor flexibilidad de tuning y mayor latencia inherente por el consenso Raft. Entender estos trade-offs a nivel de protocolo — no solo a nivel de documentación de marketing — es la competencia que distingue a un arquitecto de datos de alguien que simplemente usa una base de datos.
