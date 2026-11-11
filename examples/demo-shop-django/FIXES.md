# demo-shop (Django 5 (ORM, gunicorn)) — planted bugs and fixes

Apply these on a branch in a git worktree and run `catchme verify <worktree>` for the before/after table.

| Bug | Fix |
|---|---|
| N+1 on `GET /orders` | `prefetch_related(Prefetch('items', queryset=OrderItem.objects.select_related('product')))` |
| Missing index on `orders.user_id` | `Meta.indexes = [models.Index(fields=['user', '-created_at'])]` + migration `0002` |
| Lost update on `POST /orders` | `Product.objects.filter(id=..., stock__gte=q).update(stock=F('stock') - q)` in `transaction.atomic()`, 409 when 0 rows |
