# demo-shop (NestJS + TypeORM) — planted bugs and fixes

Apply these on a branch in a git worktree and run `catchme verify <worktree>` for the before/after table.

| Bug | Fix |
|---|---|
| N+1 on `GET /orders` | `relations: { items: { product: true } }` in `find()` |
| Missing index on `orders.user_id` | `@Index(['userId', 'createdAt'])` on `Order` |
| Lost update on `POST /orders` | QueryBuilder `update(Product).set({ stock: () => 'stock - :q' }).where('id = :id AND stock >= :q')` inside `dataSource.transaction`, 409 when `affected` is 0 |
