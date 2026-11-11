# demo-shop (FastAPI + SQLAlchemy 2 (uvicorn)) — planted bugs and fixes

Apply these on a branch in a git worktree and run `catchme verify <worktree>` for the before/after table.

| Bug | Fix |
|---|---|
| N+1 on `GET /orders` | `.options(selectinload(Order.items).joinedload(OrderItem.product))` |
| Missing index on `orders.user_id` | `Index('ix_orders_user_created', 'user_id', 'created_at')` in `__table_args__` |
| Lost update on `POST /orders` | `update(Product).where(Product.id == id, Product.stock >= q).values(stock=Product.stock - q)`, 409 when `rowcount` is 0 |
