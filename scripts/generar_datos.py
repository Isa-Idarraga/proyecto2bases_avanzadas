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