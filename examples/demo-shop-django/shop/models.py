from django.db import models


class User(models.Model):
    email = models.CharField(max_length=255, unique=True)
    password_hash = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "users"


class Product(models.Model):
    name = models.CharField(max_length=255)
    price = models.IntegerField()
    stock = models.IntegerField()

    class Meta:
        db_table = "products"


class Order(models.Model):
    # Planted problem: db_index=False — Django indexes FKs by default, this demo turns it off.
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_index=False, related_name="orders")
    status = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "orders"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, db_index=False)
    quantity = models.IntegerField()
    unit_price = models.IntegerField()

    class Meta:
        db_table = "order_items"
