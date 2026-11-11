from django.urls import path

from shop import views

urlpatterns = [
    path("health", views.health),
    path("auth/login", views.login),
    path("orders", views.orders),
    path("products/<int:product_id>", views.product),
]
