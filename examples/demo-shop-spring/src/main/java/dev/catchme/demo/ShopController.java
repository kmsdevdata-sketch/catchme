package dev.catchme.demo;

// catchme demo — intentionally contains performance and concurrency bugs.
//   1. GET /orders   N+1: items and products loaded one query at a time
//   2. GET /orders   missing index on orders.user_id (see Entities.java)
//   3. POST /orders  race: read-check-write stock update (lost update)

import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Map;
import javax.crypto.SecretKey;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
public class ShopController {
    // Demo-only default. catchme never uses production secrets.
    static final SecretKey KEY = Keys.hmacShaKeyFor(
            System.getenv().getOrDefault("JWT_SECRET", "catchme-demo-secret-catchme-demo-secret!!")
                    .getBytes(StandardCharsets.UTF_8));

    private final UserRepository users;
    private final ProductRepository products;
    private final OrderRepository orders;
    private final OrderItemRepository items;
    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();

    public ShopController(UserRepository users, ProductRepository products, OrderRepository orders, OrderItemRepository items) {
        this.users = users;
        this.products = products;
        this.orders = orders;
        this.items = items;
    }

    record LoginRequest(String email, String password) {}
    record OrderRequest(Long productId, Integer quantity) {}

    @GetMapping("/health")
    public Map<String, Object> health() {
        return Map.of("ok", true);
    }

    @PostMapping("/auth/login")
    public Map<String, String> login(@RequestBody LoginRequest body) {
        var user = users.findByEmail(String.valueOf(body.email()))
                .filter(u -> encoder.matches(String.valueOf(body.password()), u.passwordHash))
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED, "invalid credentials"));
        String token = Jwts.builder().subject(String.valueOf(user.id))
                .expiration(Date.from(Instant.now().plusSeconds(3600))).signWith(KEY).compact();
        return Map.of("token", token);
    }

    // BUG 1 + 2
    @GetMapping("/orders")
    public List<Map<String, Object>> listOrders(HttpServletRequest req, @RequestParam(defaultValue = "20") int limit) {
        long userId = AuthInterceptor.userId(req);
        var result = new ArrayList<Map<String, Object>>();
        for (Order order : orders.findByUserIdOrderByCreatedAtDesc(userId, PageRequest.of(0, Math.min(limit, 100)))) {
            var lines = new ArrayList<Map<String, Object>>();
            for (OrderItem item : items.findByOrderId(order.id)) {
                Product product = products.findById(item.productId).orElseThrow();
                lines.add(Map.of("product", product.getName(), "quantity", item.quantity, "unitPrice", item.unitPrice));
            }
            result.add(Map.of("id", order.id, "status", order.status, "createdAt", order.createdAt.toString(), "items", lines));
        }
        return result;
    }

    @GetMapping("/products/{id}")
    public Map<String, Object> product(@PathVariable long id) {
        Product p = products.findById(id).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "not found"));
        return Map.of("id", p.id, "name", p.name, "price", p.price, "stock", p.stock);
    }

    // BUG 3
    @PostMapping("/orders")
    @ResponseStatus(HttpStatus.CREATED)
    @Transactional
    public Map<String, Object> createOrder(HttpServletRequest req, @RequestBody OrderRequest body) {
        long userId = AuthInterceptor.userId(req);
        int quantity = body.quantity() == null ? 1 : body.quantity();
        Product product = products.findById(body.productId())
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "product not found"));
        if (product.getStock() < quantity) throw new ResponseStatusException(HttpStatus.CONFLICT, "out of stock");

        product.stock = product.getStock() - quantity;
        products.save(product);
        var order = new Order();
        order.userId = userId;
        order.status = "PAID";
        orders.save(order);
        var item = new OrderItem();
        item.orderId = order.id;
        item.productId = product.id;
        item.quantity = quantity;
        item.unitPrice = product.getPrice();
        items.save(item);
        return Map.of("id", order.id);
    }
}
