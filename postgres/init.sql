CREATE TABLE IF NOT EXISTS orders (
  id SERIAL PRIMARY KEY,
  created_at TIMESTAMP NOT NULL,
  status VARCHAR(20) NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
  id SERIAL PRIMARY KEY,
  order_id INT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id INT NOT NULL,
  quantity INT NOT NULL
);

TRUNCATE TABLE order_items RESTART IDENTITY CASCADE;
TRUNCATE TABLE orders RESTART IDENTITY CASCADE;

INSERT INTO orders (created_at, status)
SELECT
  (CURRENT_DATE - ((30 - gs)::text || ' days')::interval) + TIME '09:00:00',
  CASE WHEN gs IN (8, 21) THEN 'cancelled' ELSE 'completed' END
FROM generate_series(1, 30) AS gs;

INSERT INTO order_items (order_id, product_id, quantity)
SELECT
  o.id,
  1001,
  CASE
    WHEN EXTRACT(DOW FROM o.created_at) IN (1,2,3,4,5) THEN 6 + (o.id % 4)
    ELSE 3 + (o.id % 2)
  END
FROM orders o;

INSERT INTO order_items (order_id, product_id, quantity)
SELECT
  o.id,
  1002,
  CASE
    WHEN EXTRACT(DOW FROM o.created_at) IN (1,2,3,4,5) THEN 4 + (o.id % 3)
    ELSE 2 + (o.id % 2)
  END
FROM orders o;
