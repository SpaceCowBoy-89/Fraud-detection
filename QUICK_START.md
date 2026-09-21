# Quick Start — Web Dashboard

## 5-minute setup

### Step 1: Install dependencies

```bash
cd /path/to/fraud-detection
pip3 install -r requirements.txt
```

### Step 2: Configure

```bash
cp config.example.json config.json
```

Edit `config.json` or use **Settings** in the UI for:
- Affiliate API key (`api_key`)
- Admin API credentials (`admin_api`) for enrichment
- Risk thresholds and scores

### Step 3: Start the app

**Local:**

```bash
python run.py
```

**Docker (web + scheduler):**

```bash
cp .env.example .env
docker compose up -d --build
```

Open **http://localhost:5050**.

### Step 4: Fetch data

1. **Overview** or **Fetch** panel → select date range and affiliates/campaigns
2. Run fetch (free leads and/or paid sales)
3. Wait for records to land in SQLite

### Step 5: Run fraud analysis

1. **Run analysis** from the dashboard (or let the scheduler run automatically)
2. Review **Accounts** / high-risk lists

### Step 6: Record outcomes

1. **Review** tab → mark accounts **confirmed fraud** or **false positive**
2. **Effectiveness** tab → precision/recall and **Train ML model** (needs ≥30 labeled outcomes)

## Daily workflow

1. Scheduler or manual fetch for new data
2. Run analysis on new records
3. Review high-risk accounts
4. Record outcomes for model tuning

## Common issues

| Issue | Fix |
|-------|-----|
| API key not configured | Settings → affiliate API key |
| No data returned | Widen date range; check filters |
| No high-risk accounts | May be clean data, or raise thresholds in Settings |
| ML train disabled | Need 30+ reviewed outcomes; `pip install scikit-learn` |

## Operations

Production details: [docs/OPERATIONS.md](docs/OPERATIONS.md) — gunicorn, `SKIP_EMBEDDED_SCHEDULER`, backups, `/api/health/ready`.

## CSV-only workflow

Without the API, place files in `data/` and run:

```bash
python scripts/email_fraud_detector.py
```

Reports are written to `reports/`.
