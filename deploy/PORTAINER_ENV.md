# Portainer environment variables

Copy each line from your local **`.env`** (repo root, gitignored) into the stack **Environment** section, or upload `.env` if your Portainer version supports env files.

Required for **web**:

- `FLASK_SECRET_KEY`
- `FRAUD_DETECTION_API_KEY`
- `SKIP_EMBEDDED_SCHEDULER=1` (also set in compose)
- `ADMIN2_LOGIN_REQUIRED=1`
- `DB_PATH=/data/affiliate_data.db`

Required for **scheduler** (same stack):

- `FRAUD_DETECTION_API_KEY`
- `DB_PATH=/data/affiliate_data.db`
- Optional: `ADMIN_API_USERNAME`, `ADMIN_API_PASSWORD`

Image: `registry.digitalocean.com/gpdocker/fraud-detection:latest`

Compose file: `docker-compose.prod.yml`
