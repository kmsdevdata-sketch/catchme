import {
  Column,
  CreateDateColumn,
  Entity,
  Index,
  JoinColumn,
  ManyToOne,
  OneToMany,
  PrimaryGeneratedColumn,
} from 'typeorm';

@Entity({ name: 'users' })
export class User {
  @PrimaryGeneratedColumn() id: number;
  @Column({ unique: true }) email: string;
  @Column({ name: 'password_hash' }) passwordHash: string;
  @Column() name: string;
  @CreateDateColumn({ name: 'created_at' }) createdAt: Date;
}

@Entity({ name: 'products' })
export class Product {
  @PrimaryGeneratedColumn() id: number;
  @Column() name: string;
  @Column('int') price: number;
  @Column('int') stock: number;
}

// Planted problem: no index on user_id (TypeORM does not index FK columns on PostgreSQL).
@Entity({ name: 'orders' })
export class Order {
  @PrimaryGeneratedColumn() id: number;
  @Column({ name: 'user_id' }) userId: number;
  @ManyToOne(() => User) @JoinColumn({ name: 'user_id' }) user: User;
  @Column() status: string;
  @CreateDateColumn({ name: 'created_at' }) createdAt: Date;
  @OneToMany(() => OrderItem, (item) => item.order) items: OrderItem[];
}

@Entity({ name: 'order_items' })
@Index(['orderId'])
export class OrderItem {
  @PrimaryGeneratedColumn() id: number;
  @Column({ name: 'order_id' }) orderId: number;
  @ManyToOne(() => Order, (order) => order.items) @JoinColumn({ name: 'order_id' }) order: Order;
  @Column({ name: 'product_id' }) productId: number;
  @ManyToOne(() => Product) @JoinColumn({ name: 'product_id' }) product: Product;
  @Column('int') quantity: number;
  @Column('int', { name: 'unit_price' }) unitPrice: number;
}
