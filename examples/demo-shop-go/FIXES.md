# demo-shop (Go) — planted bugs and fixes

| Bug | Fix |
|---|---|
| N+1 on `GET /orders` (items per order, product per item) | one `SELECT ... FROM order_items JOIN products ... WHERE order_id = ANY($1)` for the page |
| Missing index on `orders.user_id` | `CREATE INDEX ... ON orders (user_id, created_at DESC)` (in production: `CONCURRENTLY`) |
| Lost update / oversell on `POST /orders` (`SET stock = $1` with a value computed in Go) | in one transaction: `UPDATE products SET stock = stock - $1 WHERE id = $2 AND stock >= $1 RETURNING price`; 409 when no row |
