import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="User",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.CharField(max_length=255, unique=True)),
                ("password_hash", models.CharField(max_length=255)),
                ("name", models.CharField(max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "users"},
        ),
        migrations.CreateModel(
            name="Product",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("price", models.IntegerField()),
                ("stock", models.IntegerField()),
            ],
            options={"db_table": "products"},
        ),
        migrations.CreateModel(
            name="Order",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(max_length=32)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(db_index=False, on_delete=django.db.models.deletion.CASCADE,
                                           related_name="orders", to="shop.user")),
            ],
            options={"db_table": "orders"},
        ),
        migrations.CreateModel(
            name="OrderItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("quantity", models.IntegerField()),
                ("unit_price", models.IntegerField()),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items",
                                            to="shop.order")),
                ("product", models.ForeignKey(db_index=False, on_delete=django.db.models.deletion.PROTECT,
                                              to="shop.product")),
            ],
            options={"db_table": "order_items"},
        ),
    ]
