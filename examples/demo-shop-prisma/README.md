# demo-shop

A tiny Express + Prisma shop with three planted bugs (see [FIXES.md](FIXES.md)):
N+1 on the order list, a missing index on `Order.userId`, and a lost-update race on stock.
JWT login with seeded test users (`user{n}@catchme.test` / `catchme-test`).

`.prod-parity/` already contains `seed.yaml`, `plan.yaml` and `invariants.yaml`, so the whole
flow runs without writing config:

```bash
CM=../../skills/catchme/scripts/catchme
$CM init
$CM profile --app-preset ecs-fargate:0.5vcpu-1gb --db-preset rds:db.t3.micro --latency-ms 1
$CM all              # gen → up → seed (1M orders, 2M items) → load → report
$CM breakpoint && $CM report
$CM teardown
```

Or in Claude Code with the plugin installed: "운영 사양으로 테스트해줘" / "test this with production specs".
