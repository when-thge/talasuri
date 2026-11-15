# --- frontend build -------------------------------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- backend ----------------------------------------------------------------------------
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=frontend /app/frontend/dist frontend/dist
ENV SPX_CACHE_DIR=/cache \
    SPX_FRONTEND_DIR=/app/frontend/dist
VOLUME /cache
WORKDIR /app/backend
EXPOSE 8000
CMD ["uvicorn", "spherex_viewer.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
