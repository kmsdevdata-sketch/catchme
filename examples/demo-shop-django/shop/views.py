# catchme demo — intentionally contains performance and concurrency bugs.
#   1. GET /orders   N+1: order.items and item.product loaded per row
#   2. GET /orders   missing index on orders.user_id (see models.py)
#   3. POST /orders  race: read-modify-write stock update (lost update)
import json
import os
import time

import jwt
from django.contrib.auth.hashers import check_password
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .models import Order, OrderItem, Product, User

JWT_SECRET = os.environ.get("JWT_SECRET", "catchme-demo-secret")  # demo only


def _body(request):
    try:
        return json.loads(request.body or b"{}")
    except ValueError:
        return {}


def _user_id(request):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        return int(jwt.decode(header[7:], JWT_SECRET, algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def health(request):
    return JsonResponse({"ok": True})


@require_http_methods(["POST"])
def login(request):
    data = _body(request)
    user = User.objects.filter(email=str(data.get("email", ""))).first()
    if not user or not check_password(str(data.get("password", "")), user.password_hash):
        return JsonResponse({"error": "invalid credentials"}, status=401)
    token = jwt.encode({"sub": str(user.id), "exp": int(time.time()) + 3600}, JWT_SECRET, algorithm="HS256")
    return JsonResponse({"token": token})


@require_http_methods(["GET", "POST"])
def orders(request):
    user_id = _user_id(request)
    if user_id is None:
        return JsonResponse({"error": "unauthorized"}, status=401)
    if request.method == "POST":
        return _create_order(request, user_id)
    limit = min(int(request.GET.get("limit", 20)), 100)
    result = []
    # BUG 1 + 2
    for order in Order.objects.filter(user_id=user_id).order_by("-created_at")[:limit]:
        lines = [
            {"product": item.product.name, "quantity": item.quantity, "unitPrice": item.unit_price}
            for item in order.items.all()
        ]
        result.append({"id": order.id, "status": order.status, "createdAt": order.created_at.isoformat(), "items": lines})
    return JsonResponse(result, safe=False)


def product(request, product_id):
    p = Product.objects.filter(id=product_id).first()
    if not p:
        return JsonResponse({"error": "not found"}, status=404)
    return JsonResponse({"id": p.id, "name": p.name, "price": p.price, "stock": p.stock})


# BUG 3
def _create_order(request, user_id):
    data = _body(request)
    quantity = int(data.get("quantity") or 1)
    p = Product.objects.filter(id=int(data.get("productId") or 0)).first()
    if not p:
        return JsonResponse({"error": "product not found"}, status=404)
    if p.stock < quantity:
        return JsonResponse({"error": "out of stock"}, status=409)
    p.stock -= quantity
    p.save()
    order = Order.objects.create(user_id=user_id, status="PAID")
    OrderItem.objects.create(order=order, product=p, quantity=quantity, unit_price=p.price)
    return JsonResponse({"id": order.id}, status=201)
