# SentinelAI — Déploiement VM simple (sans domaine)

Objectif: lancer l'app sur une VM avec un seul `docker compose up -d --build`, accès par IP.

## 1) Prérequis Azure

- Ouvrir dans le NSG: `5173/tcp`, `8000/tcp`, `22/tcp`.

## 2) Variables backend

Dans `backend/.env`, définir selon l'IP publique de la VM:

- `FRONTEND_URL=http://IP_VM:5173`
- `CORS_ORIGINS=http://IP_VM:5173`
- `COOKIE_SECURE=false`

## 3) Lancer la stack

```bash
docker compose up -d --build
docker compose ps
```

Accès:

- Frontend: `http://IP_VM:5173`
- API: `http://IP_VM:8000`
- Health: `http://IP_VM:8000/api/health`

## 4) Vérification

```bash
curl -I http://IP_VM:5173
curl http://IP_VM:8000/api/health
```

## Commandes utiles

```bash
docker compose down
docker compose up -d
docker compose logs -f backend
docker compose logs -f frontend
```