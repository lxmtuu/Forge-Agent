# ---------- Stage 1: build web UI ----------
FROM node:20-slim AS web
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build
# output → /build/../server/static (vite outDir '../server/static' relative to web/)
# → copy trick: build output lands in /build/../server/static = /server/static
# We copy it in stage 2 from /out below.
RUN mkdir /out && cp -r /server/static /out/static

# ---------- Stage 2: python runtime ----------
FROM python:3.12-slim AS runtime
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git curl && \
    rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY engine/ engine/
COPY server/ server/
COPY cli/ cli/
COPY scripts/ scripts/
COPY --from=web /out/static server/static
# runtime data (sessions, workspaces, config) → mount a volume here
VOLUME ["/app/data"]
ENV FORGE_DATA_DIR=/app/data
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]
