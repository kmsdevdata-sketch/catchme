# demo-shop — Go (net/http + pgx) + Redis

A stack catchme has **no detector or reference for**: plain Go `net/http`, raw SQL with pgx, a Redis
cache for product detail, bcrypt + JWT login. `init` falls back to the generic profile and the extra
service comes from `.prod-parity/compose.override.yml`. Same planted bugs as the other demos (see
[FIXES.md](FIXES.md)): N+1 on `GET /orders`, no index on `orders.user_id`, lost-update / oversell race
on `POST /orders`.

`.prod-parity/` holds the files an agent wrote when it tested this demo from scratch with only the skill:
`seed.yaml`, `plan.yaml`, `invariants.yaml` and `compose.override.yml` (Redis, plus `GOMAXPROCS=2` and
`DB_MAX_CONNS=4` because Go 1.24 and pgxpool size themselves from the host CPU count). Test users are
`user{n}@catchme.test` / `catchme-test`; the image is distroless, so the bcrypt hash in `seed.yaml` was
made in a throwaway container:

```bash
docker run --rm python:3.12-slim sh -c "pip -q install bcrypt && python -c \"import bcrypt; print(bcrypt.hashpw(b'catchme-test', bcrypt.gensalt(10)).decode())\""
```

```bash
CM=../../skills/catchme/scripts/catchme
$CM init
$CM profile --app-preset ecs-fargate:0.5vcpu-1gb --db-preset rds:db.t3.micro --latency-ms 1
$CM all
```
