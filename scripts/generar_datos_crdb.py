import psycopg2
import random
from datetime import datetime, timedelta

# Conexión a CockroachDB
conn = psycopg2.connect(
    host="localhost",
    port=26257,
    database="ecommerce_p2",
    user="root",
    password=""
)

conn.autocommit = False
cur = conn.cursor()

print("Insertando usuarios...")

# -----------------------------
# USUARIOS
# -----------------------------
regiones = ['norte', 'sur', 'centro', 'internacional']

for i in range(1, 1001):
    cur.execute("""
        INSERT INTO usuarios (nombre, email, region)
        VALUES (%s, %s, %s)
        ON CONFLICT (email) DO NOTHING
    """, (f"Usuario {i}", f"user{i}@mail.com", random.choice(regiones)))

conn.commit()

# Obtener IDs reales de usuarios (IMPORTANTE)
cur.execute("SELECT id FROM usuarios")
usuarios_ids = [row[0] for row in cur.fetchall()]

print(f"Usuarios insertados: {len(usuarios_ids)}")

# -----------------------------
# PRODUCTOS
# -----------------------------
print("Insertando productos...")

categorias = ['ropa', 'electronica', 'hogar', 'comida']

for i in range(1, 201):
    cur.execute("""
        INSERT INTO productos (nombre, categoria, precio, stock)
        VALUES (%s, %s, %s, %s)
    """, (
        f"Producto {i}",
        random.choice(categorias),
        round(random.uniform(5, 500), 2),
        random.randint(0, 1000)
    ))

conn.commit()

# -----------------------------
# PEDIDOS Y PAGOS
# -----------------------------
print("Insertando pedidos y pagos...")

estados_pedido = ['pendiente', 'pagado', 'enviado', 'cancelado']
metodos_pago = ['tarjeta', 'pse', 'efectivo', 'cripto']
fecha_inicio = datetime(2023, 1, 1)

for i in range(1, 5001):

    id_usuario = random.choice(usuarios_ids)  # CORRECCIÓN CLAVE

    fecha = fecha_inicio + timedelta(days=random.randint(0, 730))
    total = round(random.uniform(10, 2000), 2)

    cur.execute("""
        INSERT INTO pedidos (id_usuario, fecha, estado, total)
        VALUES (%s,%s,%s,%s)
        RETURNING id
    """, (id_usuario, fecha, random.choice(estados_pedido), total))

    id_pedido = cur.fetchone()[0]

    cur.execute("""
        INSERT INTO pagos (id_pedido, monto, metodo, fecha)
        VALUES (%s,%s,%s,%s)
    """, (id_pedido, total, random.choice(metodos_pago), fecha))

    if i % 500 == 0:
        conn.commit()
        print(f"{i} pedidos insertados...")

conn.commit()

# -----------------------------
# TRANSACCIONES (BATCH)
# -----------------------------
print("Insertando transacciones...")

tipos = ['compra', 'devolucion', 'pago', 'reembolso']
nodos = ['nodo1', 'nodo2', 'nodo3']

batch = []

for i in range(500000):

    fecha = fecha_inicio + timedelta(days=random.randint(0, 730))

    batch.append((
        random.choice(usuarios_ids),
        random.choice(tipos),
        round(random.uniform(1, 3000), 2),
        fecha,
        random.choice(nodos)
    ))

    if len(batch) == 5000:
        cur.executemany("""
            INSERT INTO transacciones_log 
            (id_usuario, tipo, monto, fecha, nodo_origen)
            VALUES (%s,%s,%s,%s,%s)
        """, batch)

        conn.commit()
        print(f"{i} transacciones insertadas...")
        batch = []

# Insertar lo que quede
if batch:
    cur.executemany("""
        INSERT INTO transacciones_log 
        (id_usuario, tipo, monto, fecha, nodo_origen)
        VALUES (%s,%s,%s,%s,%s)
    """, batch)
    conn.commit()

# -----------------------------
# FINALIZAR
# -----------------------------
cur.close()
conn.close()

print("Datos cargados exitosamente.")
