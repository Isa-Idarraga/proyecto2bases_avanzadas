import psycopg2
import time
import random
import statistics

conn = psycopg2.connect(
    host="localhost",
    port=26257,
    database="ecommerce_p2",
    user="root",
    password=""
)
conn.autocommit = False
cur = conn.cursor()

latencias = []
errores = 0
TOTAL = 100

print(f"Ejecutando {TOTAL} transacciones distribuidas en CockroachDB...")
print("-" * 50)

for i in range(TOTAL):
    # Elegir un producto con stock disponible
    cur.execute("SELECT id FROM productos WHERE stock > 2 ORDER BY random() LIMIT 1")
    row = cur.fetchone()
    if not row:
        errores += 1
        continue
    id_producto = row[0]

    # Elegir un pedido existente
    cur.execute("SELECT id FROM pedidos ORDER BY random() LIMIT 1")
    id_pedido = cur.fetchone()[0]

    try:
        inicio = time.time()

        cur.execute(
            "UPDATE productos SET stock = stock - 1 WHERE id = %s AND stock > 0",
            (id_producto,)
        )
        cur.execute(
            "INSERT INTO pagos (id_pedido, monto, metodo, fecha) VALUES (%s, %s, %s, NOW())",
            (id_pedido, round(random.uniform(10, 500), 2), random.choice(['tarjeta', 'pse', 'efectivo']))
        )
        cur.execute(
            "UPDATE pedidos SET estado = 'pagado' WHERE id = %s",
            (id_pedido,)
        )
        conn.commit()

        fin = time.time()
        latencia_ms = (fin - inicio) * 1000
        latencias.append(latencia_ms)

        if (i + 1) % 10 == 0:
            print(f"  Progreso: {i+1}/{TOTAL} transacciones completadas")

    except Exception as e:
        conn.rollback()
        errores += 1

cur.close()
conn.close()

# Calcular métricas
print("\n" + "=" * 50)
print("RESULTADOS — Latencia de Transacciones Distribuidas")
print("=" * 50)
print(f"Transacciones exitosas : {len(latencias)}")
print(f"Transacciones fallidas : {errores}")
print(f"Latencia promedio      : {statistics.mean(latencias):.2f} ms")
print(f"Latencia mínima        : {min(latencias):.2f} ms")
print(f"Latencia máxima        : {max(latencias):.2f} ms")
print(f"Percentil 50 (p50)     : {statistics.median(latencias):.2f} ms")
print(f"Percentil 95 (p95)     : {sorted(latencias)[int(len(latencias)*0.95)]:.2f} ms")
print(f"Percentil 99 (p99)     : {sorted(latencias)[int(len(latencias)*0.99)]:.2f} ms")
print("=" * 50)
