# Deploy on Portainer — environment **admin3-ord**

## 1. Open Portainer

Use your company Portainer URL (VPN if required).

Top-left **environment** dropdown → select **admin3-ord**.

## 2. Registry (once per environment)

**Registries → Add registry**

- Provider: **Custom** / DigitalOcean
- URL: `registry.digitalocean.com`
- Username: DigitalOcean account **email**
- Password: DigitalOcean **API token**

## 3. Create stack

**Stacks → Add stack**

| Field | Value |
|--------|--------|
| Name | `fraud-detection` |
| Build method | **Web editor** |

Paste full contents of **`deploy/admin3-ord-portainer-stack.yml`** (in this repo).

## 4. Environment variables

Scroll to **Environment variables** → **Advanced mode** (if shown).

Add each variable from your Mac **`~/fraud-detection/.env`** (gitignored):

- `FLASK_SECRET_KEY`
- `FRAUD_DETECTION_API_KEY`
- `ADMIN2_LOGIN_REQUIRED` = `1`
- `ADMIN_API_USERNAME`
- `ADMIN_API_PASSWORD`
- `PORT` = `5050`
- `IMAGE_TAG` = `latest`
- `WEBHOOK_INGEST_TOKEN` = empty (optional)

## 5. Deploy

Click **Deploy the stack**.

Both **web** and **scheduler** should show **running**.

## 6. Verify

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://<admin3-ord-host>:5050/api/health/live
```

Expect **200**. Browser: `http://<host>:5050` → admin2 login.

## 7. HTTPS

Ops: point **fraud.gptoolz.com** (or chosen hostname) to **web** service port **5050**.
