# Affiliate Fraud Detection System

Automated fraud detection and prevention system for affiliate marketing programs.

## Quick Start

### Option 1: CLI Application (Recommended)

```bash
cd ~/fraud-detection
pip install -r requirements.txt
python cli_app.py
```

### Option 2: Direct Script Analysis

```bash
cd ~/fraud-detection
pip install pandas numpy openpyxl
python scripts/email_fraud_detector.py
```

Place CSV/Excel exports in `data/` directory, review results in `reports/`.

## Features

- **Rich CLI Interface** - Beautiful terminal UI with grouped menus and shortcuts
- **API Integration** - Fetch data directly from affiliate tracking platforms
- **Advanced Fraud Detection** - 15+ pattern detection algorithms
- **Config-Driven Scoring** - Adjust all risk scores without code changes
- **Outcome Tracking** - Record and learn from confirmed fraud cases
- **Effectiveness Metrics** - Track detection precision over time
- **Billing Correlation** - Detect shared payment fraud rings
- **Unit Tests** - Comprehensive test coverage

## Project Structure

```
fraud-detection/
├── cli_app.py           # CLI application (v3.0)
├── cli/                 # CLI modules
│   ├── helpers.py       # UI utilities
│   └── menu.py          # Menu system
├── scripts/
│   └── email_fraud_detector.py  # Detection engine
├── tests/               # Unit tests
├── data/                # CSV exports (gitignored)
├── reports/             # Generated reports
├── config.json          # Configuration (created on first run)
├── CLAUDE.md            # AI assistant guide
└── README_CLI.md        # Detailed CLI documentation
```

## What It Detects

### Email Patterns
- Name-number patterns (john43murphy5398@gmail.com)
- Excessive dots (a.b.c.d.e@domain.com)
- Digit suffixes (user12345@domain.com)
- Scrambled usernames (xkjhgfds@domain.com)
- Written numbers (emillythree@domain.com)
- Suspicious names (from configurable list)

### Behavioral Signals
- POV validation timing (< 60 seconds = fraud indicator)
- Desktop vs mobile (90% of legit users are mobile)
- IP velocity (many signups from same IP)
- Geographic clustering

### Billing Correlations
- Same card across multiple accounts
- Same billing name variations
- IP addresses with multiple cards

## Risk Scoring

All scores are configurable in `config.json`:

| Pattern | Default Score |
|---------|---------------|
| Name-number pattern | 40 |
| POV instant (≤20s) | 50 |
| POV fast (≤40s) | 40 |
| Scrambled pattern | 35 |
| Suspicious name | 30 |
| Desktop Windows 10 | 20 |
| Excessive dots | 20 |
| Digit suffix | 15 |

**Risk Levels:**
- 🔴 High Risk: ≥50 points
- 🟡 Medium Risk: 25-49 points
- 🟢 Low Risk: <25 points

## Documentation

| File | Description |
|------|-------------|
| `README_CLI.md` | Full CLI documentation with all features |
| `CLAUDE.md` | AI assistant context and fraud patterns |
| `RISK_SCORES.md` | Detailed risk score explanations |
| `ADVANCED_FEATURES_GUIDE.md` | ML and advanced analytics |

## Running Tests

```bash
python -m pytest tests/ -v
```

## Support

This system is designed to work with Claude Code. Start a new session in the `fraud-detection` directory and Claude will automatically load context from `CLAUDE.md`.
