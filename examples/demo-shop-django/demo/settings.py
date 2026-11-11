import os

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "catchme-demo-only-secret")  # demo only
DEBUG = os.environ.get("DEBUG", "False") == "True"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = ["shop"]
MIDDLEWARE = ["django.middleware.common.CommonMiddleware"]
ROOT_URLCONF = "demo.urls"
WSGI_APPLICATION = "demo.wsgi.application"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "NAME": os.environ.get("DB_NAME", "app"),
        "USER": os.environ.get("DB_USER", "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "postgres"),
        # Django default: a new connection per request (CONN_MAX_AGE=0)
        "CONN_MAX_AGE": int(os.environ.get("CONN_MAX_AGE", "0")),
    }
}
