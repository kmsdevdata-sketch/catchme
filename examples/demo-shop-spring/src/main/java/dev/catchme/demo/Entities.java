package dev.catchme.demo;

import jakarta.persistence.*;
import java.time.Instant;

@Entity
@Table(name = "users")
class User {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) Long id;
    @Column(nullable = false, unique = true) String email;
    @Column(name = "password_hash", nullable = false) String passwordHash;
    @Column(nullable = false) String name;
    @Column(name = "created_at", nullable = false) Instant createdAt = Instant.now();
}

@Entity
@Table(name = "products")
class Product {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) Long id;
    @Column(nullable = false) String name;
    @Column(nullable = false) int price;
    @Column(nullable = false) int stock;

    // Accessors matter: a LAZY association can hand you a Hibernate proxy, whose fields are never populated.
    String getName() { return name; }
    int getPrice() { return price; }
    int getStock() { return stock; }
}

// Planted problem: no index on user_id (JPA/Hibernate does not index FK columns on PostgreSQL).
@Entity
@Table(name = "orders")
class Order {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) Long id;
    @Column(name = "user_id", nullable = false) Long userId;
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", insertable = false, updatable = false)
    User user;
    @Column(nullable = false) String status;
    @Column(name = "created_at", nullable = false) Instant createdAt = Instant.now();
}

@Entity
@Table(name = "order_items", indexes = @Index(name = "ix_order_items_order_id", columnList = "order_id"))
class OrderItem {
    @Id @GeneratedValue(strategy = GenerationType.IDENTITY) Long id;
    @Column(name = "order_id", nullable = false) Long orderId;
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "order_id", insertable = false, updatable = false)
    Order order;
    @Column(name = "product_id", nullable = false) Long productId;
    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "product_id", insertable = false, updatable = false)
    Product product;
    @Column(nullable = false) int quantity;
    @Column(name = "unit_price", nullable = false) int unitPrice;
}
