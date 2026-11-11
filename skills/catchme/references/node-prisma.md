# Node + Prisma reference

## Detection signals
- `package.json` with `prisma` / `@prisma/client`; `prisma/schema.prisma` (`provider = "postgresql"`).
- Web framework: Express / Fastify (`app.get(...)`, `router.post(...)`), NestJS (`@Controller`, `@Get`).
- Port: `process.env.PORT || 3000`, `listen(3000)`. Default 3000.

## Dockerfile (if the project has none)
Use `templates/dockerfiles/node-prisma.Dockerfile`. Prisma needs `openssl` in slim images.
Migrations at start: `npx prisma migrate deploy` if `prisma/migrations/` exists, else `npx prisma db push --skip-generate`.

## DB wiring
`gen` sets `DATABASE_URL=postgresql://app_user:app_password@toxiproxy:15432/app?connection_limit=<pool>&pool_timeout=10`.
If the app reads a different variable, add it to `project.json → app.env` (point it at `toxiproxy:15432`).

## Connection pool — production gotcha
Prisma's default pool is `num_physical_cpus * 2 + 1`. Inside a container Node sees the **host's**
CPUs, not the cgroup limit, so the pool size differs between laptop and Fargate. catchme sets
`connection_limit` explicitly (profile `app.db_pool_size`, default 5 — what a 2-vCPU-visible
Fargate task gets). Pool exhaustion shows as `P2024` "Timed out fetching a new connection" → 5xx.

## N+1 patterns and fixes
| Pattern | Evidence in metrics | Fix |
|---|---|---|
| `findMany` then `findUnique`/`findMany` per row in a loop | one `SELECT ... WHERE "id" = $1` with calls ≈ rows × requests | `include` / nested `select` (Prisma batches into `IN (...)`) |
| `Promise.all(rows.map(r => prisma.x.findUnique(...)))` | same, but concurrent — still N queries | `include`, or one `findMany({ where: { id: { in: ids } } })` |
| Fluent API `prisma.user.findUnique().posts()` in loops | per-row SELECT | `include` |
| Counting in loop | `SELECT COUNT(*)` per row | `_count` in `select` / `groupBy` |

Prisma's `include` is 1 query per relation level (not a JOIN) — expect queries/request ≈ 1 + depth.

## Race patterns and fixes
| Pattern | Fix |
|---|---|
| read `stock`, check, `update({ data: { stock: product.stock - qty } })` (lost update) | atomic `update({ data: { stock: { decrement: qty } }, where: { id, stock: { gte: qty } } })` via `updateMany` and check `count` |
| check-then-insert (unique coupons, seats) | unique constraint + catch `P2002`, or `SELECT ... FOR UPDATE` in `$transaction` with `$queryRaw` |
| multi-step write without transaction | `prisma.$transaction([...])` or interactive transaction with `isolationLevel: 'Serializable'` + retry |

## Missing index
Prisma does **not** create indexes for relation scalar fields on PostgreSQL. A `where: { userId }`
on a big table → Seq Scan. Fix: `@@index([userId])` (or `@@index([userId, createdAt])` when ordered).

## Hooks patterns
`schema.prisma`, `*repository*.ts|js`, service files that call `prisma.` (add a glob to `hooks.enabled`).
