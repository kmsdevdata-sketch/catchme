import 'reflect-metadata';
import { Module } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import { TypeOrmModule } from '@nestjs/typeorm';
import { Order, OrderItem, Product, User } from './entities';
import { ShopController } from './shop.controller';

@Module({
  imports: [
    TypeOrmModule.forRoot({
      type: 'postgres',
      host: process.env.DB_HOST || 'localhost',
      port: Number(process.env.DB_PORT || 5432),
      username: process.env.DB_USERNAME || 'postgres',
      password: process.env.DB_PASSWORD || 'postgres',
      database: process.env.DB_DATABASE || 'app',
      entities: [User, Product, Order, OrderItem],
      synchronize: true, // demo only
      extra: { max: Number(process.env.DB_POOL_SIZE || 10) },
    }),
    TypeOrmModule.forFeature([User, Product, Order, OrderItem]),
  ],
  controllers: [ShopController],
})
class AppModule {}

async function bootstrap() {
  const app = await NestFactory.create(AppModule, { logger: ['error', 'warn', 'log'] });
  await app.listen(process.env.PORT || 3000);
  console.log(`demo-shop-nest-typeorm listening on ${process.env.PORT || 3000}`);
}
bootstrap();
