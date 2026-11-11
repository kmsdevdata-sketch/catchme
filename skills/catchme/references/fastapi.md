# FastAPI + SQLAlchemy reference

## Detection signals
- `requirements.txt` / `pyproject.toml` with `fastapi`, `sqlalchemy`, `psycopg` or `asyncpg`.
- Endpoints: `@app.get("/...")`, `@router.post(...)` with `APIRouter(prefix=...)`.
- Port: 8000 (uvicorn/gunicorn command in Dockerfile / Procfile).

## Dockerfile (if the project has none)
Use `templates/dockerfiles/fastapi.Dockerfile`. Run like production: `uvicorn --workers N` or
`gunicorn -k uvicorn.workers.UvicornWorker`. 0.5 vCPU → 1–2 workers. Run Alembic (`alembic upgrade head`)
before start if the project uses it.

## DB wiring
`gen` sets `DATABASE_URL=postgresql+psycopg://app_user:app_password@toxiproxy:15432/app`
(`postgresql+asyncpg://` when the project is async) and `DB_POOL_SIZE`. If settings use another
name (`SQLALCHEMY_DATABASE_URI`, pydantic `Settings`), map it in `project.json → app.env`.

## Connections — production gotcha
SQLAlchemy's pool is **per worker process**: `pool_size` (default 5) + `max_overflow` (default 10).
Total connections ≈ workers × (pool_size + max_overflow). Sync endpoints run in a 40-thread pool,
so a single worker can ask for far more connections than `pool_size` → `QueuePool limit ... timeout`
→ 500s. Compare totals with the RDS class `max_connections`.

## N+1 patterns and fixes
| Pattern | Evidence | Fix |
|---|---|---|
| default `lazy="select"` relationship accessed in a loop (`order.items`, `item.product`) | per-row SELECT, calls ≈ rows × requests | `options(selectinload(Order.items).joinedload(OrderItem.product))` |
| Pydantic `from_attributes` serializing relationships | lazy loads during response serialization | eager-load in the query; `lazy="raise"` to catch it in tests |
| async session lazy load | `MissingGreenlet` errors | always eager-load in async code |

`selectinload` = 1 extra query per relation level (`IN (...)`) → queries/request ≈ 1 + depth.

## Race patterns and fixes
| Pattern | Fix |
|---|---|
| `p = session.get(Product, id); p.stock -= q; commit()` | `update(Product).where(Product.id == id, Product.stock >= q).values(stock=Product.stock - q)` and check `rowcount` |
| check-then-insert | unique constraint + `IntegrityError` |
| multi-row consistency | `select(...).with_for_update()` inside one transaction |

## Missing index
`ForeignKey` columns are not indexed automatically. `mapped_column(ForeignKey("users.id"), index=True)` or
`Index("ix_orders_user_created", Order.user_id, Order.created_at.desc())`.

## Hooks patterns
`models.py`, `crud.py`, `repository.py`, `services/*.py`.
