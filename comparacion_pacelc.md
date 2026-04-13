# Análisis Comparativo PACELC — PostgreSQL Distribuido vs CockroachDB

## 1. ¿Qué es el modelo PACELC?

El teorema CAP establece que ante una **partición de red (P)**, un sistema
distribuido debe elegir entre **Disponibilidad (A)** o **Consistencia (C)**.
El modelo PACELC extiende esto: cuando no hay partición **(E — Else)**, el
sistema igual enfrenta un trade-off entre **Latencia (L)** y
**Consistencia (C)**.

Esto da cuatro clasificaciones posibles:
- **PA/EL** — ante partición elige disponibilidad; sin partición elige latencia
- **PA/EC** — ante partición elige disponibilidad; sin partición elige consistencia
- **PC/EL** — ante partición elige consistencia; sin partición elige latencia
- **PC/EC** — ante partición elige consistencia; sin partición elige consistencia

---

## 2. Clasificación PACELC de cada motor

### PostgreSQL distribuido

| Escenario | Comportamiento observado | Clasificación |
|---|---|---|
| Partición de red | En modo `synchronous_commit = off`, el primary sigue aceptando escrituras aunque las réplicas no confirmen. Puede haber pérdida de datos si el primary cae. Elige **disponibilidad**. | **PA** |
| Sin partición | Con `synchronous_commit = on`, espera confirmación de todas las réplicas antes de responder. Mayor latencia pero mayor consistencia. Con `off`, responde inmediatamente sacrificando consistencia. Configurable — por defecto elige **latencia**. | **EL** |
| **Clasificación total** | | **PA/EL** |

### CockroachDB

| Escenario | Comportamiento observado | Clasificación |
|---|---|---|
| Partición de red | En la simulación con iptables (sección 3.3), el nodo aislado rechazó consultas por no poder alcanzar quórum. El clúster prefirió no responder antes que responder con datos potencialmente desactualizados. Elige **consistencia**. | **PC** |
| Sin partición | Raft requiere que la mayoría de réplicas confirmen cada escritura antes de responder al cliente. Esto añade latencia de consenso (promedio 18.59 ms medido en sección 3.4) pero garantiza consistencia serializable. Elige **consistencia**. | **EC** |
| **Clasificación total** | | **PC/EC** |

---

## 3. Tabla comparativa en 7 dimensiones

| Dimensión | PostgreSQL distribuido | CockroachDB |
|---|---|---|
| **Particionamiento** | Manual. Isabella es¡cribió DDL explícito con `PARTITION BY RANGE` y `PARTITION BY HASH`. Requiere conocer la distribución de datos anticipadamente. | Automático. El motor divide las tablas en rangos de 512 MB y los redistribuye sin intervención. La app no necesita saber dónde están los datos. |
| **Replicación** | Configurable entre síncrona (`synchronous_commit = on`) y asíncrona (`off`). Juan José midió latencia de escritura síncrona en 7.77 ms y asíncrona en 1.81 ms. | Siempre basada en consenso Raft. Cada escritura requiere quórum (2 de 3 nodos). No hay modo asíncrono — la consistencia no es negociable. |
| **Consistencia** | Configurable. En modo asíncrono puede haber lag de replicación — réplicas con datos desactualizados. En modo síncrono es fuerte pero con mayor latencia. | Serializabilidad por defecto en todas las transacciones. No hay niveles de aislamiento más débiles disponibles para escrituras distribuidas. |
| **Latencia de escritura** | Asíncrona: 7.77 ms. Síncrona: 1.81 ms. (Datos de Juan José) | Transacción distribuida (3 operaciones): promedio 18.59 ms, p95 23.46 ms, p99 73.59 ms. |
| **Transacciones distribuidas** | 2PC manual. Requiere `PREPARE TRANSACTION` en cada nodo y `COMMIT PREPARED` como coordinador. Si el coordinador cae entre fases, los recursos quedan bloqueados hasta intervención manual. | `BEGIN/COMMIT` estándar. El motor gestiona el protocolo de consenso internamente. Rollback automático garantizado ante cualquier fallo. |
| **Tolerancia a fallos** | Failover manual con `pg_promote()` o herramientas como Patroni. Juan José midió un tiempo de failover de 35 segundos. Requiere un DBA disponible o automatización externa. | Failover automático por Raft: 5091 ms (~5 segundos). Sin intervención humana. |
| **Complejidad operativa** | Alta. Requiere configurar `pg_hba.conf`, `postgresql.conf`, replicación, Patroni o repmgr, monitoreo de lag, y un DBA especializado en PostgreSQL distribuido. | Baja para operaciones. El clúster se autogestiona: balanceo de rangos, elección de líderes, reintegración de nodos caídos. La complejidad está en entender el modelo de consistencia, no en la operación diaria. |

---

## 4. Análisis de costos operativos

### PostgreSQL distribuido (autoalojado)

Operar PostgreSQL distribuido en producción requiere al menos:
- Un DBA senior con experiencia en replicación y alta disponibilidad
- Infraestructura propia o EC2 con almacenamiento persistente por nodo
- Herramientas adicionales: Patroni o repmgr para failover automático,
  PgBouncer para pooling de conexiones, Prometheus + Grafana para monitoreo
- Tiempo de respuesta ante incidentes: el failover manual implica disponibilidad
  humana 24/7

Costo estimado en AWS (3 nodos `r6g.large` + almacenamiento + DBA):
aproximadamente **USD 800–1.500/mes** dependiendo de la región y el tamaño
del equipo de operaciones.

### CockroachDB administrado (CockroachDB Serverless / Dedicated)

CockroachDB Cloud elimina la gestión de infraestructura:
- Sin DBA dedicado para operaciones de replicación o failover
- Escala automática de almacenamiento y cómputo
- SLA de 99.99% de disponibilidad incluido
- Respaldo automático y cifrado en reposo

Costo estimado para la misma carga:
- **Serverless**: gratuito hasta 10 GiB, luego ~USD 1/GiB/mes
- **Dedicated**: desde ~USD 300/mes por clúster de 3 nodos

El ahorro real no está solo en el costo directo sino en el costo de
oportunidad del DBA, que puede dedicarse a desarrollo en lugar de
operaciones de infraestructura.

---

## 5. Análisis crítico — ¿cuándo usar cada uno?

### Usa PostgreSQL distribuido cuando:

**Tienes un equipo DBA consolidado y necesitas control total.**
Empresas como Mercado Libre y Rappi comenzaron con PostgreSQL porque
ya tenían equipos con experiencia en el motor y necesitaban flexibilidad
para tunear parámetros específicos de replicación según la criticidad
de cada tabla — transacciones financieras con `synchronous_commit = on`,
logs de actividad con `synchronous_commit = off`.

**El esquema es estable y los patrones de acceso son predecibles.**
PostgreSQL distribuido funciona mejor cuando sabes de antemano cómo
particionar — por región, por rango de fechas, por hash de usuario.
El esfuerzo de diseño inicial que hizo Isabella se amortiza cuando
las consultas siempre acceden a la misma partición.

**Tienes restricciones regulatorias sobre dónde viven los datos.**
PostgreSQL te da control exacto sobre en qué nodo físico reside cada
partición, lo que permite cumplir regulaciones de residencia de datos
como la Ley 1581 de Colombia o el GDPR europeo de forma explícita.

### Usa CockroachDB cuando:

**Estás construyendo un producto nuevo sin equipo DBA especializado.**
Startups como Faire y Bose adoptaron CockroachDB porque les permitió
tener una base de datos distribuida con consistencia fuerte sin contratar
un equipo de infraestructura de datos. El auto-sharding y el failover
automático reducen la carga operativa a casi cero.

**Necesitas escalar geográficamente sin rediseñar el esquema.**
CockroachDB soporta geodistribución nativa — puedes agregar nodos en
nuevas regiones y el motor redistribuye los rangos automáticamente.
Con PostgreSQL tendrías que rediseñar el esquema de particionamiento
y migrar datos manualmente.

**La consistencia es innegociable y no puedes permitir pérdida de datos.**
En sistemas financieros donde cada transacción debe ser atómica a través
de múltiples nodos — transferencias bancarias, inventarios en tiempo real,
reservas de vuelos — el modelo PC/EC de CockroachDB elimina la clase entera
de bugs que produce el 2PC manual de PostgreSQL.

---

## 6. Impacto en la administración — DBA vs servicio administrado

| Responsabilidad | DBA con PostgreSQL | CockroachDB administrado |
|---|---|---|
| Configurar replicación | Manual, archivo por archivo | Automático al crear el clúster |
| Responder a failover | Disponibilidad 24/7 requerida | Motor lo resuelve solo |
| Escalar almacenamiento | Agregar nodos + rebalanceo manual | Un slider en la consola |
| Actualizar el motor | Ventana de mantenimiento planificada | Rolling updates sin downtime |
| Monitorear lag de replicación | Consultas manuales o Grafana | Dashboard integrado |
| Costo humano mensual | Alto (perfil senior especializado) | Bajo (cualquier desarrollador opera) |

La diferencia fundamental es que con PostgreSQL distribuido **la complejidad
vive en el equipo humano**, mientras que con CockroachDB **la complejidad
vive dentro del motor**. Ninguno es gratuito — simplemente está en un lugar
diferente.
