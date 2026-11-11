# catchme template — Node + Prisma. Copy to .prod-parity/app.Dockerfile and adjust.
# Build context is the project root.
FROM node:20-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssl ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package*.json ./
COPY prisma ./prisma
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY . .
RUN npx prisma generate && (npm run build --if-present)
ENV NODE_ENV=production
EXPOSE 3000
# migrate deploy when migrations exist, otherwise push the schema
CMD ["sh", "-c", "if [ -d prisma/migrations ]; then npx prisma migrate deploy; else npx prisma db push --skip-generate; fi && npm start"]
