# catchme demo — intentionally contains performance and concurrency bugs.
#   1. GET /orders   N+1: lazy relationships (order.items, item.product) loaded per row
#   2. GET /orders   missing index on orders.user_id (see models.py)
#   3. POST /orders  race: read-modify-write stock update (lost update)
import os
import time

import bcrypt
import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from .models import Order, OrderItem, Product, User

JWT_SECRET = os.environ.get("JWT_SECRET", "catchme-demo-secret")  # demo only

app = FastAPI()


class LoginIn(BaseModel):
    email: str = ""
    password: str = ""


class OrderIn(BaseModel):
    productId: int
    quantity: int = 1


def current_user(authorization: str = Header(default="")) -> int:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing token")
    try:
        return int(jwt.decode(authorization[7:], JWT_SECRET, algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "invalid token")


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_session)):
    user = db.scalar(select(User).where(User.email == body.email))
    if not user or not bcrypt.checkpw(body.password.encode(), user.password_hash.encode()):
        raise HTTPException(401, "invalid credentials")
    token = jwt.encode({"sub": str(user.id), "exp": int(time.time()) + 3600}, JWT_SECRET, algorithm="HS256")
    return {"token": token}


# BUG 1 + 2
@app.get("/orders")
def list_orders(limit: int = 20, user_id: int = Depends(current_user), db: Session = Depends(get_session)):
    orders = db.scalars(
        select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(min(limit, 100))
    ).all()
    return [
        {
            "id": o.id,
            "status": o.status,
            "createdAt": o.created_at.isoformat(),
            "items": [{"product": i.product.name, "quantity": i.quantity, "unitPrice": i.unit_price} for i in o.items],
        }
        for o in orders
    ]


@app.get("/products/{product_id}")
def product(product_id: int, db: Session = Depends(get_session)):
    p = db.get(Product, product_id)
    if not p:
        raise HTTPException(404, "not found")
    return {"id": p.id, "name": p.name, "price": p.price, "stock": p.stock}


# BUG 3
@app.post("/orders", status_code=201)
def create_order(body: OrderIn, user_id: int = Depends(current_user), db: Session = Depends(get_session)):
    p = db.get(Product, body.productId)
    if not p:
        raise HTTPException(404, "product not found")
    if p.stock < body.quantity:
        raise HTTPException(409, "out of stock")
    p.stock = p.stock - body.quantity
    db.commit()
    order = Order(user_id=user_id, status="PAID")
    db.add(order)
    db.flush()
    db.add(OrderItem(order_id=order.id, product_id=p.id, quantity=body.quantity, unit_price=p.price))
    db.commit()
    return {"id": order.id}
