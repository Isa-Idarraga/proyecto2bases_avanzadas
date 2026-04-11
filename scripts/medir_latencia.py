import psycopg2
import time
import random
from datetime import datetime, timedelta
import sys

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
        print(f"  [{modo}] insercion {i+1}/100", flush=True)

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

print("Experimento: Latencia escritura sincrona vs asincrona", flush=True)
print("=" * 55, flush=True)
medir_latencia("on")
medir_latencia("off")