# Node + TypeORM reference (NestJS / Express)

## Detection signals
- `package.json` with `typeorm` (+ `pg`); NestJS adds `@nestjs/core`, `@nestjs/typeorm`.
- Entities: `@Entity()` classes (`*.entity.ts`). Endpoints: `@Controller('orders')` + `@Get()`, or Express routes.
- Port: `app.listen(process.env.PORT || 3000)`. Default 3000.

## Dockerfile (if the project has none)
Use `templates/dockerfiles/node-typeorm.Dockerfile` (multi-stage: `npm run build` → `node dist/main.js`).
Schema at start: migrations (`typeorm migration:run`) if the project has them, otherwise `synchronize: true`
in a test-only config. Never point `synchronize` at a shared database.

## DB wiring
`gen` sets `DB_HOST/DB_PORT/DB_USERNAME/DB_PASSWORD/DB_DATABASE/DB_POOL_SIZE` and `DATABASE_URL`.
TypeORM config is code, so check that the DataSource / `TypeOrmModule.forRoot` reads these (or map the
names it does read in `project.json → app.env`). Pool size goes in `extra: { max: Number(process.env.DB_POOL_SIZE) }`
(node-postgres pool, default 10).

## N+1 patterns and fixes
| Pattern | Evidence | Fix |
|---|---|---|
| `find()` then `findOne`/`findBy` per row in a loop | one SELECT with calls ≈ rows × requests | `relations: { items: { product: true } }` or QueryBuilder `leftJoinAndSelect` |
| `lazy: true` relations awaited in a loop (`await order.items`) | per-row SELECT | eager load with `relations` / join |
| `eager: true` everywhere | huge joins on every query | explicit `relations` per query |

`relations` in `find()` produces JOINs → queries/request ≈ 1–2.

## Race patterns and fixes
| Pattern | Fix |
|---|---|
| `findOneBy` → `product.stock -= q` → `save(product)` (lost update) | `createQueryBuilder().update(Product).set({ stock: () => 'stock - :q' }).where('id = :id AND stock >= :q')` and check `affected` |
| check-then-insert | unique constraint + catch `23505` |
| multi-step write | `dataSource.transaction(async (m) => ...)` with `lock: { mode: 'pessimistic_write' }` when needed |

## Missing index
TypeORM does not index FK columns automatically on PostgreSQL. Add `@Index(['user', 'createdAt'])` on the entity
(or a migration).

## Hooks patterns
`*.entity.ts`, `*.service.ts`, `*repository*.ts`.
