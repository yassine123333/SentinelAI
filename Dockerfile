# syntax=docker/dockerfile:1

FROM node:20-bookworm AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libffi8 \
    libjpeg62-turbo \
    libxml2 \
    libxslt1.1 \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
