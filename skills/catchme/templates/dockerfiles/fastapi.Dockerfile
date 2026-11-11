# catchme template — FastAPI under uvicorn. Copy to .prod-parity/app.Dockerfile and adjust the
# module path (app.main:app) and worker count (match production).
# Build context is the project root.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
ENV WEB_CONCURRENCY=2
CMD ["sh", "-c", "if [ -f alembic.ini ]; then alembic upgrade head; fi && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY}"]
