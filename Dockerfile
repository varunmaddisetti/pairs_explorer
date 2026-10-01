# Optional container route. Not required for the local demo (use `make demo`).
FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/ backend/
COPY config/ config/
COPY data/demo/ data/demo/
COPY scripts/ scripts/
COPY --from=ui /ui/dist frontend/dist
ENV PDE_SOURCE=synthetic PYTHONPATH=/app/backend
EXPOSE 8000
# Inside the container we bind 0.0.0.0; docker-compose publishes it on 127.0.0.1 only.
CMD ["python", "-m", "uvicorn", "app.api.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
