// catchme demo — intentionally contains performance and concurrency bugs.
//   1. GET /orders   N+1: items and products loaded one query at a time
//   2. GET /orders   missing index on orders.user_id (see entities.ts)
//   3. POST /orders  race: read-check-write stock update (lost update)
import {
  Body,
  CanActivate,
  ConflictException,
  Controller,
  ExecutionContext,
  Get,
  HttpCode,
  Injectable,
  NotFoundException,
  Param,
  Post,
  Query,
  Req,
  UnauthorizedException,
  UseGuards,
} from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import * as bcrypt from 'bcryptjs';
import * as jwt from 'jsonwebtoken';
import { Repository } from 'typeorm';
import { Order, OrderItem, Product, User } from './entities';

// Demo-only default. catchme never uses production secrets.
const JWT_SECRET = process.env.JWT_SECRET || 'catchme-demo-secret';

@Injectable()
export class JwtGuard implements CanActivate {
  canActivate(ctx: ExecutionContext): boolean {
    const req = ctx.switchToHttp().getRequest();
    const header: string = req.headers['authorization'] || '';
    if (!header.startsWith('Bearer ')) throw new UnauthorizedException('missing token');
    try {
      const payload = jwt.verify(header.slice(7), JWT_SECRET) as jwt.JwtPayload;
      req.userId = Number(payload.sub);
      return true;
    } catch {
      throw new UnauthorizedException('invalid token');
    }
  }
}

@Controller()
export class ShopController {
  constructor(
    @InjectRepository(User) private readonly users: Repository<User>,
    @InjectRepository(Product) private readonly products: Repository<Product>,
    @InjectRepository(Order) private readonly orders: Repository<Order>,
    @InjectRepository(OrderItem) private readonly items: Repository<OrderItem>,
  ) {}

  @Get('health')
  health() {
    return { ok: true };
  }

  @Post('auth/login')
  @HttpCode(200)
  async login(@Body() body: { email?: string; password?: string }) {
    const user = await this.users.findOneBy({ email: String(body?.email || '') });
    if (!user || !(await bcrypt.compare(String(body?.password || ''), user.passwordHash))) {
      throw new UnauthorizedException('invalid credentials');
    }
    return { token: jwt.sign({ sub: String(user.id) }, JWT_SECRET, { expiresIn: '1h' }) };
  }

  // BUG 1 + 2
  @Get('orders')
  @UseGuards(JwtGuard)
  async listOrders(@Req() req: any, @Query('limit') limitParam?: string) {
    const limit = Math.min(Number(limitParam) || 20, 100);
    const orders = await this.orders.find({
      where: { userId: req.userId },
      order: { createdAt: 'DESC' },
      take: limit,
    });
    const result = [];
    for (const order of orders) {
      const items = await this.items.findBy({ orderId: order.id });
      const lines = [];
      for (const item of items) {
        const product = await this.products.findOneBy({ id: item.productId });
        lines.push({ product: product.name, quantity: item.quantity, unitPrice: item.unitPrice });
      }
      result.push({ id: order.id, status: order.status, createdAt: order.createdAt, items: lines });
    }
    return result;
  }

  @Get('products/:id')
  async product(@Param('id') id: string) {
    const product = await this.products.findOneBy({ id: Number(id) });
    if (!product) throw new NotFoundException('not found');
    return product;
  }

  // BUG 3
  @Post('orders')
  @UseGuards(JwtGuard)
  async createOrder(@Req() req: any, @Body() body: { productId?: number; quantity?: number }) {
    const productId = Number(body?.productId);
    const quantity = Number(body?.quantity) || 1;
    const product = await this.products.findOneBy({ id: productId });
    if (!product) throw new NotFoundException('product not found');
    if (product.stock < quantity) throw new ConflictException('out of stock');

    product.stock = product.stock - quantity;
    await this.products.save(product);
    const order = await this.orders.save(this.orders.create({ userId: req.userId, status: 'PAID' }));
    await this.items.save(this.items.create({ orderId: order.id, productId, quantity, unitPrice: product.price }));
    return { id: order.id };
  }
}
