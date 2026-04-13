#!/bin/bash

NODO_A_BAJAR="crdb_node1"
NODO_CONSULTA="crdb_node2"

echo "=== Experimento de Failover CockroachDB ==="
echo "Nodo que se va a bajar: $NODO_A_BAJAR"
echo ""

# Estado inicial
echo "--- Estado inicial ---"
docker exec $NODO_CONSULTA ./cockroach node status \
--insecure \
--host=$NODO_CONSULTA:26257 | head -5

# Tiempo inicio
INICIO=$(date +%s%3N)

echo ""
echo "Bajando nodo a las: $(date '+%H:%M:%S.%3N')"
docker stop $NODO_A_BAJAR > /dev/null

echo "Esperando recuperación del clúster..."

INTENTOS=0

while true; do
  RESULTADO=$(docker exec $NODO_CONSULTA ./cockroach sql \
    --insecure \
    --host=$NODO_CONSULTA:26257 \
    --execute="USE ecommerce_p2; SELECT count(*) FROM transacciones_log;" \
    2>&1)

  INTENTOS=$((INTENTOS + 1))

  # ✔ Solo verificar que la query funcione (no valor exacto)
  if echo "$RESULTADO" | grep -q "count"; then
    FIN=$(date +%s%3N)
    DURACION=$((FIN - INICIO))

    echo ""
    echo "✓ Clúster recuperado a las: $(date '+%H:%M:%S.%3N')"
    echo "✓ Tiempo de failover: ${DURACION} ms"
    echo "✓ Intentos hasta recuperación: $INTENTOS"
    break
  fi

  sleep 1
done

echo ""
echo "--- Estado de nodos después del failover ---"
docker exec $NODO_CONSULTA ./cockroach node status \
--insecure \
--host=$NODO_CONSULTA:26257

echo ""
echo "--- Leaseholders actuales ---"

docker exec $NODO_CONSULTA ./cockroach sql \
--insecure \
--host=$NODO_CONSULTA:26257 \
--execute="USE ecommerce_p2;
SELECT lease_holder, count(*) AS rangos
FROM [SHOW RANGES FROM TABLE transacciones_log WITH DETAILS]
GROUP BY lease_holder
ORDER BY lease_holder;"

# Levantar nodo nuevamente
echo ""
echo "Levantando $NODO_A_BAJAR nuevamente..."
docker start $NODO_A_BAJAR

echo "Hecho."
