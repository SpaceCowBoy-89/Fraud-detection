# Affiliate Fraud Detection System

Automated fraud detection and prevention system for affiliate marketing programs.

## Quick Start

### Web dashboard (recommended)

```bash
cd ~/fraud-detection
pip install -r requirements.txt
cp config.example.json config.json   # add API keys
python run.py
```

Open **http://localhost:5050** (default port 5050).

**Docker (web + scheduler):**

```bash
docker compose up -d --build
```

See [docs/OPERATIONS.md](docs/OPERATIONS.md) for scheduler, backups, and health checks.

### Direct script analysis (CSV/Excel only)

```bash
python scripts/email_fraud_detector.py
```

Place exports in `data/`, review results in `reports/`.

## Features

- **Web dashboard** — Fetch, analyze, review outcomes, ML training, EDA, metrics
- **Scheduled pipeline** — Automated fetch and analyze (`scheduler.py` or Docker `scheduler` service)
- **API integration** — Fetch data from affiliate tracking platforms
- **Advanced fraud detection** — 15+ pattern detection algorithms
- **Config-driven scoring** — Adjust risk scores in `config.json`
- **Outcome tracking** — Confirmed fraud / false positive labels for precision metrics
- **Supervised ML** — Logistic regression on reviewed outcomes (ROC-AUC)
- **Billing correlation** — Shared payment fraud rings
- **Unit tests** — `pytest tests/`

## Project Structure

```
fraud-detection/
├── run.py               # Web app entry point
├── wsgi.py              # Gunicorn WSGI app
├── scheduler.py         # Automated fetch + analyze pipeline
├── dashboard/           # Flask API + UI
├── scripts/             # Detection, EDA, ML, enrichment
├── database.py          # SQLite persistence
├── api_client.py        # Affiliate API
├── config.json          # Settings (from config.example.json)
├── data/                # CSV exports (gitignored)
├── reports/             # Script-generated reports
└── docs/OPERATIONS.md   # Production operations
```

## What It Detects

### Email Patterns
- Name-number patterns (john43murphy5398@gmail.com)
- Excessive dots, digit suffixes, scrambled usernames
- Suspicious names (configurable list)

### Behavioral Signals
- POV validation timing, IP velocity, geographic clustering
- Admin enrichment: shared cards, Amex/business cards, IP geo, profile image timing

### Billing Correlations
- Same card across multiple accounts
- Same billing name variations

## Risk Scoring

Configurable in `config.json`. Default high-risk threshold: **50**.

| Pattern | Default Score |
|---------|---------------|
| Name-number pattern | 40 |
| POV instant (≤20s) | 50 |
| Scrambled pattern | 35 |
| Suspicious name | 30 |

## Documentation

| File | Description |
|------|-------------|
| `QUICK_START.md` | Web dashboard setup |
| `docs/OPERATIONS.md` | Docker, scheduler, backups |
| `CLAUDE.md` | Patterns and architecture for AI assistants |

## Running Tests

```bash
python -m pytest tests/ -v
```
