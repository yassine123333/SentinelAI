# SentinelAI — Docker Deployment Guide

This guide explains how to pull and run SentinelAI from Docker Hub, including the required environment structure.

## Image

- Docker Hub repository: `yassineamri/sentinelai-one`
- Recommended tag: `latest`
- Pinned tag example: `20260220`

---

## 1) Prerequisites

- Docker installed and running
- Internet access to pull images
- Open host port (`8000` by default)

---

## 2) Create runtime environment file

Copy the template and fill your real secrets:

```bash
cp .env.docker.example .env.sentinelai
```

Edit `.env.sentinelai` and set at least:

- `JWT_SECRET_KEY`
- `GROQ_API_KEY`
- `MONGODB_URI` (default works with the Mongo container below)
- `CORS_ORIGINS`
- `COOKIE_SECURE` (`true` in HTTPS production)

---

## 3) Pull image

```bash
docker pull yassineamri/sentinelai-one:latest
# or pinned version
# docker pull yassineamri/sentinelai-one:20260220
```

---

## 4) Run MongoDB and app

```bash
# Create isolated network
docker network create sentinelai-net

# Start MongoDB
docker run -d \
  --name sentinelai-mongo \
  --network sentinelai-net \
  -v sentinelai-mongo-data:/data/db \
  mongo:7

# Start SentinelAI app
docker run -d \
  --name sentinelai-app \
  --network sentinelai-net \
  --env-file .env.sentinelai \
  -p 8000:8000 \
  yassineamri/sentinelai-one:latest
```

If port `8000` is already in use:

```bash
docker rm -f sentinelai-app
docker run -d \
  --name sentinelai-app \
  --network sentinelai-net \
  --env-file .env.sentinelai \
  -p 18000:8000 \
  yassineamri/sentinelai-one:latest
```

---

## 5) Validate deployment

```bash
docker ps
docker logs -f sentinelai-app
curl http://localhost:8000/api/health
```

If running on port `18000`:

```bash
curl http://localhost:18000/api/health
```

Open app in browser:

- `http://localhost:8000` (or `http://localhost:18000`)

---

## 6) Stop / restart / cleanup

```bash
# Stop
docker stop sentinelai-app sentinelai-mongo

# Start
docker start sentinelai-mongo sentinelai-app

# Remove containers
docker rm -f sentinelai-app sentinelai-mongo

# Remove network
docker network rm sentinelai-net

# Remove Mongo data volume (WARNING: deletes DB data)
docker volume rm sentinelai-mongo-data
```

---

## Notes

- Frontend is built into the Docker image at build time.
- Runtime `VITE_*` variables are not applied unless the image is rebuilt.
- For production, run behind HTTPS and set:
  - `COOKIE_SECURE=true`
  - `CORS_ORIGINS=https://your-domain`
  - strong `JWT_SECRET_KEY`
