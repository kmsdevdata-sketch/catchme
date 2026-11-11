# demo-shop (Spring Boot 3 + JPA (Hibernate)) — planted bugs and fixes

Apply these on a branch in a git worktree and run `catchme verify <worktree>` for the before/after table.

| Bug | Fix |
|---|---|
| N+1 on `GET /orders` | `@EntityGraph(attributePaths = "product") findByOrderIdIn(ids)` — 2 queries instead of 1 + N + N×M |
| Missing index on `orders.user_id` | `@Table(indexes = @Index(columnList = "user_id, created_at"))` |
| Lost update on `POST /orders` | `@Modifying @Query("update Product p set p.stock = p.stock - :q where p.id = :id and p.stock >= :q")`, 409 when it returns 0 |
