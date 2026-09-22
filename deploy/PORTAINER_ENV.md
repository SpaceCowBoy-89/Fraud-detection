# Portainer environment variables

Copy each line from your local **`.env`** (repo root, gitignored) into the stack **Environment** section, or upload `.env` if your Portainer version supports env files.

Required for **web**:

- `FLASK_SECRET_KEY` — generate once: `python -c "import secrets; print(secrets.token_hex(32))"`
- `REQUIRE_FLASK_SECRET_KEY=1` — already set in `docker-compose.prod.yml` / Portainer stack
- `FRAUD_DETECTION_API_KEY`
- `SKIP_EMBEDDED_SCHEDULER=1` (also set in compose)
- `ADMIN2_LOGIN_REQUIRED=1`
- `DB_PATH=/data/affiliate_data.db`

HTTPS / reverse-proxy (already defaulted on in prod compose):

- `SESSION_COOKIE_SECURE=1` — marks session cookies Secure (required when users hit HTTPS)
- `TRUST_PROXY_HTTPS=1` — treat `X-Forwarded-Proto: https` as secure (TLS terminator / Portainer proxy)

Required for **scheduler** (same stack):

- `FRAUD_DETECTION_API_KEY`
- `DB_PATH=/data/affiliate_data.db`
- Optional: `ADMIN_API_USERNAME`, `ADMIN_API_PASSWORD`

Image: `registry.digitalocean.com/gpdocker/fraud-detection:latest`

Compose file: `docker-compose.prod.yml` (or `deploy/admin3-ord-portainer-stack.yml`)

Checklist before go-live:

1. `FLASK_SECRET_KEY` is non-empty in Portainer env (rotating it forces re-login)
2. Stack uses prod compose so `REQUIRE_FLASK_SECRET_KEY=1` and Secure cookie defaults apply
3. Site is served over HTTPS (or Secure cookies will not stick on plain HTTP)
