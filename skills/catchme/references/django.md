# Django (ORM) reference

## Detection signals
- `manage.py`, `settings.py` with `DATABASES` (`django.db.backends.postgresql`), `urls.py` with `path(...)`.
- DRF: `rest_framework` in `INSTALLED_APPS`, `routers.DefaultRouter()`.
- Port: 8000 (gunicorn/uvicorn config may differ — check Procfile / Dockerfile).

## Dockerfile (if the project has none)
Use `templates/dockerfiles/django.Dockerfile`. Run under **gunicorn** like production, not
`runserver` (single-threaded, debug overhead). Workers: production value, or `2 * cpus + 1` rounded
(0.5 vCPU → 2 workers). Run `python manage.py migrate --noinput` before start.

## DB wiring
`gen` sets `DATABASE_URL=postgres://app_user:app_password@toxiproxy:15432/app` and
`DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD`. Settings vary a lot:
- `dj-database-url` / `django-environ` → `DATABASE_URL` works.
- Hard-coded `DATABASES` → add the env names it reads to `project.json → app.env`, or a
  `DJANGO_SETTINGS_MODULE` test settings file under `.prod-parity/` that reads them.
Also set `DEBUG=False` (DEBUG keeps every query in memory) and `ALLOWED_HOSTS=*` (test only).

## Connections — production gotcha
Django has no pool by default: `CONN_MAX_AGE=0` opens a connection per request — with 1 ms+ latency
and TLS in production, that is expensive. Mirror production's `CONN_MAX_AGE` /
`CONN_HEALTH_CHECKS` (Django 4.1+) or psycopg3 pool (`OPTIONS: {"pool": ...}`, Django 5.1+).
Connections ≈ workers × threads. Compare with `max_connections` of the RDS class.

## N+1 patterns and fixes
| Pattern | Evidence | Fix |
|---|---|---|
| FK access in loop / template / serializer (`order.user.email`) | `SELECT ... WHERE "id" = %s` calls ≈ rows × requests | `select_related('user')` |
| reverse FK / M2M in loop (`order.items.all()`) | per-row SELECT on child | `prefetch_related('items')`, `Prefetch(...)` with queryset |
| DRF nested serializers | same | override `get_queryset()` with `select_related`/`prefetch_related` |
| `.count()` per row | `SELECT COUNT(*)` per row | `annotate(n=Count('items'))` |

## Race patterns and fixes
| Pattern | Fix |
|---|---|
| `p = Product.objects.get(...); p.stock -= q; p.save()` | `Product.objects.filter(id=..., stock__gte=q).update(stock=F('stock') - q)` and check rowcount |
| check-then-create | unique constraint + `IntegrityError`, or `get_or_create` (still needs a unique constraint) |
| multi-row consistency | `transaction.atomic()` + `select_for_update()` |

## Missing index
Django creates indexes for `ForeignKey` automatically, so missing-index findings are usually on
filter/order columns: add `Meta.indexes = [models.Index(fields=["user", "-created_at"])]`.

## Hooks patterns
`models.py`, `managers.py`, `querysets.py`, `serializers.py` (add to `hooks.enabled`), `views.py` if queries live there.
