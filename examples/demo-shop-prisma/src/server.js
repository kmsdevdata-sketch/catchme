// catchme demo shop — intentionally contains performance and concurrency bugs.
//   1. GET /orders      N+1: items and products are loaded one query at a time
//   2. GET /orders      missing index on Order.userId (see prisma/schema.prisma)
//   3. POST /orders     race: read-check-write stock update (lost update)
// See FIXES.md for the fixed versions.
const crypto = require('crypto');
const express = require('express');
const jwt = require('jsonwebtoken');
const { PrismaClient } = require('@prisma/client');

const prisma = new PrismaClient();
const app = express();
app.use(express.json());

// Demo-only default. catchme never uses production secrets.
const JWT_SECRET = process.env.JWT_SECRET || 'catchme-demo-secret';

// Password format: scrypt$<salt>$<hex(scrypt(password, salt, 64))>
function verifyPassword(password, stored) {
  const [algo, salt, hash] = String(stored).split('$');
  if (algo !== 'scrypt' || !salt || !hash) return false;
  const derived = crypto.scryptSync(password, salt, 64);
  const expected = Buffer.from(hash, 'hex');
  return expected.length === derived.length && crypto.timingSafeEqual(derived, expected);
}

function auth(req, res, next) {
  const header = req.get('authorization') || '';
  const token = header.startsWith('Bearer ') ? header.slice(7) : null;
  if (!token) return res.status(401).json({ error: 'missing token' });
  try {
    const payload = jwt.verify(token, JWT_SECRET);
    req.userId = Number(payload.sub);
    return next();
  } catch (e) {
    return res.status(401).json({ error: 'invalid token' });
  }
}

app.get('/health', (req, res) => res.json({ ok: true }));

app.post('/auth/login', async (req, res, next) => {
  try {
    const { email, password } = req.body || {};
    const user = await prisma.user.findUnique({ where: { email: String(email || '') } });
    if (!user || !verifyPassword(String(password || ''), user.passwordHash)) {
      return res.status(401).json({ error: 'invalid credentials' });
    }
    const token = jwt.sign({ sub: String(user.id) }, JWT_SECRET, { expiresIn: '1h' });
    return res.json({ token });
  } catch (e) {
    return next(e);
  }
});

// BUG 1 + 2: N+1 queries, and `where: { userId }` scans Order without an index.
app.get('/orders', auth, async (req, res, next) => {
  try {
    const limit = Math.min(Number(req.query.limit) || 20, 100);
    const orders = await prisma.order.findMany({
      where: { userId: req.userId },
      orderBy: { createdAt: 'desc' },
      take: limit,
    });
    const result = [];
    for (const order of orders) {
      const items = await prisma.orderItem.findMany({ where: { orderId: order.id } });
      const lines = [];
      for (const item of items) {
        const product = await prisma.product.findUnique({ where: { id: item.productId } });
        lines.push({ product: product.name, quantity: item.quantity, unitPrice: item.unitPrice });
      }
      result.push({ id: order.id, status: order.status, createdAt: order.createdAt, items: lines });
    }
    return res.json(result);
  } catch (e) {
    return next(e);
  }
});

app.get('/products/:id', async (req, res, next) => {
  try {
    const product = await prisma.product.findUnique({ where: { id: Number(req.params.id) } });
    if (!product) return res.status(404).json({ error: 'not found' });
    return res.json(product);
  } catch (e) {
    return next(e);
  }
});

// BUG 3: read stock, check, then write `stock - quantity` — concurrent requests overwrite each other.
app.post('/orders', auth, async (req, res, next) => {
  try {
    const productId = Number(req.body.productId);
    const quantity = Number(req.body.quantity) || 1;
    const product = await prisma.product.findUnique({ where: { id: productId } });
    if (!product) return res.status(404).json({ error: 'product not found' });
    if (product.stock < quantity) return res.status(409).json({ error: 'out of stock' });

    await prisma.product.update({
      where: { id: productId },
      data: { stock: product.stock - quantity },
    });
    const order = await prisma.order.create({
      data: {
        userId: req.userId,
        status: 'PAID',
        items: { create: [{ productId, quantity, unitPrice: product.price }] },
      },
    });
    return res.status(201).json({ id: order.id });
  } catch (e) {
    return next(e);
  }
});

// eslint-disable-next-line no-unused-vars
app.use((err, req, res, next) => {
  console.error(err.message);
  res.status(500).json({ error: 'internal error' });
});

const port = Number(process.env.PORT || 3000);
app.listen(port, () => console.log(`demo-shop listening on ${port}`));
