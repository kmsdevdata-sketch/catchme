# catchme template — Django under gunicorn. Copy to .prod-parity/app.Dockerfile and adjust
# the WSGI module (myproject.wsgi) and worker count (match production).
# Build context is the project root.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn psycopg[binary]
COPY . .
EXPOSE 8000
ENV GUNICORN_WORKERS=2
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn myproject.wsgi:application --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS}"]
