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