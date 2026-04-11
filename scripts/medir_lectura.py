import psycopg2
import time
import sys

def medir_lectura(nombre, puerto, n=100):
    conn = psycopg2.connect(
        host="localhost", port=puerto,
        database="ecommerce_p2",
        user="postgres", password="postgres123"
    )
    cur = conn.cursor()
    tiempos = []

    for i in range(n):
        inicio = time.perf_counter()
        cur.execute("""
            SELECT id_usuario, SUM(monto), COUNT(*)
            FROM transacciones_log
            WHERE fecha BETWEEN '2023-01-01' AND '2023-06-30'
            GROUP BY id_usuario
            ORDER BY SUM(monto) DESC
            LIMIT 10;
        """)
        cur.fetchall()
        fin = time.perf_counter()
        tiempos.append((fin - inicio) * 1000)

    tiempos.sort()
    promedio = sum(tiempos) / len(tiempos)
    p95 = tiempos[int(len(tiempos) * 0.95)]
    p99 = tiempos[int(len(tiempos) * 0.99)]

    print(f"\nNodo: {nombre} (puerto {puerto})", flush=True)
    print(f"  Promedio : {promedio:.2f} ms", flush=True)
    print(f"  P95      : {p95:.2f} ms", flush=True)
    print(f"  P99      : {p99:.2f} ms", flush=True)
    print(f"  Minimo   : {min(tiempos):.2f} ms", flush=True)
    print(f"  Maximo   : {max(tiempos):.2f} ms", flush=True)

    cur.close()
    conn.close()

print("Experimento: Latencia de lectura Primary vs Replica", flush=True)
print("=" * 55, flush=True)
medir_lectura("Primary (pg_replica1 promovido)", 5434)
medir_lectura("Replica 2", 5435)