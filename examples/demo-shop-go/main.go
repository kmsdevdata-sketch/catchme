// demo-shop-go — Go net/http + pgx + Redis, no ORM. Same planted bugs as the other demos:
//  1. GET /orders   N+1: items and products loaded one query at a time
//  2. GET /orders   missing index on orders.user_id
//  3. POST /orders  race: read stock, check, write the computed value (lost update / oversell)
//
// GET /products/{id} is cached in Redis (catchme has no built-in Redis: the agent adds it).
package main

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
	"golang.org/x/crypto/bcrypt"
)

var (
	db        *pgxpool.Pool
	cache     *redis.Client
	jwtSecret = []byte(getenv("JWT_SECRET", "dev-secret-change-me"))
)

const schema = `
CREATE TABLE IF NOT EXISTS users (
  id BIGSERIAL PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
  name TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS products (
  id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, price INT NOT NULL, stock INT NOT NULL);
CREATE TABLE IF NOT EXISTS orders (
  id BIGSERIAL PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES users(id), status TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS order_items (
  id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL REFERENCES orders(id),
  product_id BIGINT NOT NULL REFERENCES products(id), quantity INT NOT NULL, unit_price INT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_order_items_order_id ON order_items(order_id);`

func getenv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func fail(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}

func userID(r *http.Request) (int64, bool) {
	h := r.Header.Get("Authorization")
	if !strings.HasPrefix(h, "Bearer ") {
		return 0, false
	}
	tok, err := jwt.Parse(h[7:], func(t *jwt.Token) (any, error) { return jwtSecret, nil },
		jwt.WithValidMethods([]string{"HS256"}))
	if err != nil || !tok.Valid {
		return 0, false
	}
	sub, _ := tok.Claims.GetSubject()
	id, err := strconv.ParseInt(sub, 10, 64)
	return id, err == nil
}

func login(w http.ResponseWriter, r *http.Request) {
	var in struct{ Email, Password string }
	_ = json.NewDecoder(r.Body).Decode(&in)
	var id int64
	var hash string
	err := db.QueryRow(r.Context(), "SELECT id, password_hash FROM users WHERE email = $1", in.Email).Scan(&id, &hash)
	if err != nil || bcrypt.CompareHashAndPassword([]byte(hash), []byte(in.Password)) != nil {
		fail(w, http.StatusUnauthorized, "invalid credentials")
		return
	}
	tok, _ := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub": strconv.FormatInt(id, 10), "exp": time.Now().Add(time.Hour).Unix(),
	}).SignedString(jwtSecret)
	writeJSON(w, http.StatusOK, map[string]string{"token": tok})
}

type line struct {
	Product   string `json:"product"`
	Quantity  int    `json:"quantity"`
	UnitPrice int    `json:"unitPrice"`
}

type order struct {
	ID        int64     `json:"id"`
	Status    string    `json:"status"`
	CreatedAt time.Time `json:"createdAt"`
	Items     []line    `json:"items"`
}

func listOrders(w http.ResponseWriter, r *http.Request) {
	uid, ok := userID(r)
	if !ok {
		fail(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	ctx := r.Context()
	rows, err := db.Query(ctx, "SELECT id, status, created_at FROM orders WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2", uid, limit)
	if err != nil {
		fail(w, 500, err.Error())
		return
	}
	orders, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (order, error) {
		var o order
		err := row.Scan(&o.ID, &o.Status, &o.CreatedAt)
		return o, err
	})
	if err != nil {
		fail(w, 500, err.Error())
		return
	}
	for i := range orders {
		items, err := db.Query(ctx, "SELECT product_id, quantity, unit_price FROM order_items WHERE order_id = $1", orders[i].ID)
		if err != nil {
			fail(w, 500, err.Error())
			return
		}
		type item struct {
			productID  int64
			qty, price int
		}
		list, err := pgx.CollectRows(items, func(row pgx.CollectableRow) (item, error) {
			var it item
			err := row.Scan(&it.productID, &it.qty, &it.price)
			return it, err
		})
		if err != nil {
			fail(w, 500, err.Error())
			return
		}
		orders[i].Items = []line{}
		for _, it := range list {
			var name string
			if err := db.QueryRow(ctx, "SELECT name FROM products WHERE id = $1", it.productID).Scan(&name); err != nil {
				fail(w, 500, err.Error())
				return
			}
			orders[i].Items = append(orders[i].Items, line{name, it.qty, it.price})
		}
	}
	writeJSON(w, http.StatusOK, orders)
}

func getProduct(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	ctx := r.Context()
	if cached, err := cache.Get(ctx, "product:"+id).Result(); err == nil {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(cached))
		return
	}
	var p struct {
		ID    int64  `json:"id"`
		Name  string `json:"name"`
		Price int    `json:"price"`
		Stock int    `json:"stock"`
	}
	err := db.QueryRow(ctx, "SELECT id, name, price, stock FROM products WHERE id = $1", id).Scan(&p.ID, &p.Name, &p.Price, &p.Stock)
	if errors.Is(err, pgx.ErrNoRows) {
		fail(w, http.StatusNotFound, "not found")
		return
	} else if err != nil {
		fail(w, 500, err.Error())
		return
	}
	b, _ := json.Marshal(p)
	cache.Set(ctx, "product:"+id, b, time.Minute)
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write(b)
}

func createOrder(w http.ResponseWriter, r *http.Request) {
	uid, ok := userID(r)
	if !ok {
		fail(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	var in struct {
		ProductID int64 `json:"productId"`
		Quantity  int   `json:"quantity"`
	}
	_ = json.NewDecoder(r.Body).Decode(&in)
	if in.Quantity == 0 {
		in.Quantity = 1
	}
	ctx := r.Context()
	var stock, price int
	if err := db.QueryRow(ctx, "SELECT stock, price FROM products WHERE id = $1", in.ProductID).Scan(&stock, &price); err != nil {
		fail(w, http.StatusNotFound, "product not found")
		return
	}
	if stock < in.Quantity {
		fail(w, http.StatusConflict, "out of stock")
		return
	}
	if _, err := db.Exec(ctx, "UPDATE products SET stock = $1 WHERE id = $2", stock-in.Quantity, in.ProductID); err != nil {
		fail(w, 500, err.Error())
		return
	}
	var oid int64
	if err := db.QueryRow(ctx, "INSERT INTO orders (user_id, status) VALUES ($1, 'PAID') RETURNING id", uid).Scan(&oid); err != nil {
		fail(w, 500, err.Error())
		return
	}
	if _, err := db.Exec(ctx, "INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES ($1, $2, $3, $4)",
		oid, in.ProductID, in.Quantity, price); err != nil {
		fail(w, 500, err.Error())
		return
	}
	cache.Del(ctx, "product:"+strconv.FormatInt(in.ProductID, 10))
	writeJSON(w, http.StatusCreated, map[string]int64{"id": oid})
}

func main() {
	ctx := context.Background()
	cfg, err := pgxpool.ParseConfig(getenv("DATABASE_URL", "postgres://postgres:postgres@localhost:5432/app"))
	if err != nil {
		log.Fatal(err)
	}
	if n, err := strconv.Atoi(os.Getenv("DB_MAX_CONNS")); err == nil && n > 0 {
		cfg.MaxConns = int32(n)
	}
	if db, err = pgxpool.NewWithConfig(ctx, cfg); err != nil {
		log.Fatal(err)
	}
	if _, err := db.Exec(ctx, schema); err != nil {
		log.Fatal(err)
	}
	opt, err := redis.ParseURL(getenv("REDIS_URL", "redis://localhost:6379/0"))
	if err != nil {
		log.Fatal(err)
	}
	cache = redis.NewClient(opt)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) { writeJSON(w, 200, map[string]bool{"ok": true}) })
	mux.HandleFunc("POST /auth/login", login)
	mux.HandleFunc("GET /orders", listOrders)
	mux.HandleFunc("POST /orders", createOrder)
	mux.HandleFunc("GET /products/{id}", getProduct)
	addr := ":" + getenv("PORT", "8080")
	log.Printf("demo-shop-go listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}
