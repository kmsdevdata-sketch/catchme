# demo-shop — planted bugs and their fixes

catchme should find all three. Apply these on a branch in a git worktree and run
`catchme verify <worktree>` to get the before/after table.

## 1. N+1 on `GET /orders`
1 + 20 + (20 × items) queries per request. With 1 ms app↔DB latency that alone costs ~60 ms.

```js
const orders = await prisma.order.findMany({
  where: { userId: req.userId },
  orderBy: { createdAt: 'desc' },
  take: limit,
  include: { items: { include: { product: { select: { name: true } } } } },
});
```
Prisma issues one query per relation level → 3 queries per request.

## 2. Missing index on `Order.userId`
`where: { userId } orderBy createdAt` scans 1M orders.

```prisma
model Order {
  // ...
  @@index([userId, createdAt])
}
```

## 3. Race on `POST /orders` (lost update)
Concurrent requests read the same stock and each write `stock - 1`.

```js
const updated = await prisma.product.updateMany({
  where: { id: productId, stock: { gte: quantity } },
  data: { stock: { decrement: quantity } },
});
if (updated.count === 0) return res.status(409).json({ error: 'out of stock' });
// create the order in the same $transaction as the decrement
```
