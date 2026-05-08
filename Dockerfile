# ─── Stage 1: Build Next.js frontend ────────────────────────────────────────
FROM node:20-alpine AS frontend-builder
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --silent
COPY frontend/ ./
RUN npm run build

# ─── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM python:3.11-slim

# Node.js runtime (for the Next.js standalone server)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Python backend
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ .

# Next.js standalone bundle
COPY --from=frontend-builder /build/.next/standalone /app/frontend
COPY --from=frontend-builder /build/.next/static     /app/frontend/.next/static
COPY --from=frontend-builder /build/public           /app/frontend/public

RUN mkdir -p /app/data

COPY entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh

EXPOSE 3000 8000
WORKDIR /app
CMD ["/app/entrypoint.sh"]
