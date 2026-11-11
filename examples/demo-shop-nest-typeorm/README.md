# demo-shop — NestJS + TypeORM

Same shop as the other demos (users, products, orders, order items; JWT login) with the same three
planted bugs in `src/shop.controller.ts` and `src/entities.ts`:

1. **N+1** on `GET /orders` — items and products are loaded one query at a time
2. **Missing index** on `orders.user_id`
3. **Race** on `POST /orders` — read-check-write stock update (lost update)

`.prod-parity/` contains `seed.yaml`, `plan.yaml` and `invariants.yaml`. Test users are
`user{n}@catchme.test` / `catchme-test`; the password hash (bcryptjs) is computed **inside the app
container with the app's own encoder** and pasted into `seed.yaml` (already filled in; to regenerate, put `__PASSWORD_HASH__` back and run the hash line below):

```bash
CM=../../skills/catchme/scripts/catchme
$CM init
$CM profile --app-preset ecs-fargate:0.5vcpu-1gb --db-preset rds:db.t3.micro --latency-ms 1
$CM gen && $CM up
$CM exec app node -e "console.log(require('bcryptjs').hashSync('catchme-test', 10))"
$CM seed && $CM load && $CM report
```

See [FIXES.md](FIXES.md) for the fixed version.
