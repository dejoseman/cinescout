# ---------------------------------------------------------------------------
# CineScout - single container serving the API and the compiled application.
# ---------------------------------------------------------------------------

# Stage 1: build the React application.
FROM node:22-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# Vite is configured to emit into ../backend/static, so redirect it here.
RUN npm run build -- --outDir dist --emptyOutDir


# Stage 2: the Python service.
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1     PYTHONDONTWRITEBYTECODE=1     PIP_NO_CACHE_DIR=1     PORT=8080

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend /build/dist ./static

# Run as a non-root user.
RUN useradd --create-home --uid 1001 cinescout && chown -R cinescout:cinescout /app
USER cinescout

EXPOSE 8080

# Cloud Run supplies $PORT; concurrency is bounded in application config.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
