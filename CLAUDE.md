# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an **Affiliate Fraud Detection and Prevention System** focused on analyzing affiliate marketing data to identify fraudulent accounts and estimate revenue loss. The system processes CSV exports from three primary data sources:

1. **Affiliate tracking platforms** - Lead generation and conversion data
2. **Internal databases** - Account creation and validation data
3. **Payment processors** - Transaction and billing information

**Scale**: 100+ affiliates daily, with focus on first sales from new accounts (created < 4 hours ago)

## Project Structure

```
fraud-detection/
├── cli_app.py              # Main CLI application (v3.0) - RECOMMENDED
├── cli_fraud_detection.py  # Legacy CLI (still works)
├── cli/                    # CLI modules
│   ├── helpers.py          # UI utilities, responsive tables
│   └── menu.py             # Menu system, shortcuts
├── scripts/                # Analysis scripts
│   └── email_fraud_detector.py
├── tests/                  # Unit tests
│   ├── test_email_fraud_detector.py
│   └── test_database.py
├── data/                   # Place CSV exports here
│   ├── Leads.csv
│   └── Sales.csv
├── reports/                # Generated fraud detection reports
├── config.json             # Configuration (risk scores, API key)
└── docs/                   # Additional documentation
```

## Data Sources and Formats

### Leads.csv
**Source**: Affiliate tracking platforms
**Fields**: `email`, `IP`, `DUID`, `username`, `payout amount`, `campaign`, `Ad Id`, `transaction date`

### Sales.csv
**Source**: Payment processors
**Fields**: `first name`, `last name`, `email`, `IP`, `sale amount`, `payout amount`, `campaign`, `DUID`, `Ad Id`, `transaction date`

### Manual Enhancement Fields (Added via internal platform)
- `account_creation_timestamp`
- `email_validation_timestamp`
- `validation_time_seconds` (calculated)

## Fraud Detection Patterns

### Priority 1: Email Validation Timing (HIGHEST IMPACT)
**Pattern**: Email validated within 60 seconds of account creation
**Manual Process**: Export timestamps from internal platform, calculate time difference
**Automation Status**: Framework ready, pending automatic timestamp export

### Email Pattern Detection (AUTOMATED)
Detects:
- **Excessive dots**: >3 dots in email username (+25 risk points)
- **Digit suffix**: 4-5 digits at end of username (+20 risk points)
- **Scrambled patterns**: Low vowel ratio indicating random generation (+35 risk points)
- **Name-Number pattern**: firstname+number+lastname+number structure (+40 risk points)
  - Examples: `john43murphy5398@gmail.com`, `bradley93sanders5984@gmail.com`
- **Suspicious names**: Known fraud-associated names (fatima, oduwale, olatunde, muhammed, mohammed) (+30 risk points)
- **Domain concentration**: >90% traffic from same non-major domain (+30 risk points)
- **Theme clustering**: Related email themes (real estate, construction, crypto, finance) (+15 risk points)

**Risk Scoring**:
- 0-24: Low Risk
- 25-49: Medium Risk
- 50-100: High Risk

### Additional Patterns (NOT YET AUTOMATED)
**Internal Database Indicators**:
- Fake content (reverse image search needed)
- Geolocation mismatch (registration IP ≠ login IP)

**Payment Processor Indicators**:
- Same/similar billing names across accounts
- Credit card connected to multiple accounts
- Transaction clusters from same card issuer (excluding Bank of America, JP Morgan Chase, Capital One, Citi)
- Multiple business cards from same issuer

## Running Fraud Detection

### Option 1: CLI Application (Recommended)
```bash
cd ~/fraud-detection

# Install dependencies (first time only)
pip install -r requirements.txt

# Launch CLI
python cli_app.py
```

**CLI Features:**
- Grouped menu (Data, Detection, Analysis, Review, System)
- Quick shortcuts: `f` (fetch), `r` (run), `v` (view), `a` (alerts), `h` (help)
- Press `b` to go back in any submenu
- Config-driven risk scores (edit `config.json`)

### Option 2: Direct Script Analysis
```bash
cd ~/fraud-detection

# Run interactively (select from available files)
python scripts/email_fraud_detector.py

# OR specify file directly
python scripts/email_fraud_detector.py data/your_leads_file.xlsx
```

**Requirements**:
- Python 3.7+
- pandas, numpy, openpyxl (install via `pip install -r requirements.txt`)

**Supported File Formats**:
- CSV (.csv)
- Excel (.xls, .xlsx)

**Input**: Place your data files in `data/` directory
**Output**:
- `reports/{filename}_fraud_report.csv` - Complete analysis with risk scores
- `reports/{filename}_fraud_report_HIGH_RISK.csv` - Priority investigation list (risk >= 50)

**Workflow**:
1. Export data from affiliate tracking platform (CSV or Excel format)
2. Place in `data/` directory
3. Run script (interactive mode will list all available files)
4. Review HIGH_RISK report for immediate action
5. Use account identifiers to create Asana tasks for developer review

**Note**: Output files are automatically named based on your input file name

## Current Limitations and Future Automation

### No API Access Currently
Data exports are manual. Future automation requires:
1. **Real-time email validation timing** - Most critical fraud indicator
2. **Account creation webhooks** - Catch fraud within 4-hour window
3. **Scheduled data exports** - Even automated CSV exports would help

### Developer Discussion Points
When requesting API access, prioritize:
1. Email validation timestamp endpoints
2. Account creation event hooks
3. Scheduled export automation

## Workflow Integration

### Current Manual Process
1. Export CSVs from platforms
2. Run fraud detection scripts
3. Review high-risk accounts
4. Document findings in BookStack (screenshots + analysis)
5. Create Asana tasks for flagged accounts
6. Assign developers for investigation
7. Review fixes in production
8. Monitor Metabase/Kibana for patterns

### Automation Opportunities
- **Testing & Documentation**: Separate automation track (see Documentation chat)
- **Asana Integration**: Separate automation track (see Asana Integration chat)
- **Metabase Dashboards**: Separate automation track (see Metabase chat)

## Risk Score Customization

All risk scores are now **config-driven**. Edit `config.json` to adjust:

```json
{
  "risk_scores": {
    "excessive_dots": 20,
    "digit_suffix": 15,
    "scrambled_pattern": 35,
    "name_number_pattern": 40,
    "written_number_pattern": 15,
    "repeated_word_pattern": 25,
    "suspicious_name": 30,
    "pov_instant_20s": 50,
    "pov_instant_40s": 40,
    "pov_fast_60s": 30,
    "ip_velocity_high": 30,
    "desktop_windows_10": 20,
    "us_state_cluster": 25,
    "us_city_state_cluster": 30,
    "intl_country_city_cluster": 30
  },
  "suspicious_names": ["fatima", "muhammed"],
  "risk_thresholds": {
    "high": 50,
    "medium": 25
  }
}
```

Changes take effect immediately on next analysis run - no code changes needed.

## Cross-Reference Analysis (Future)

To connect Leads and Sales data:
1. Use `DUID` field present in both CSVs
2. Track first-sale timing relative to account creation
3. Calculate revenue impact of flagged fraudulent accounts using `sale amount` and `payout amount`
4. Priority: New accounts (created < 4 hours) making first purchase

## Notes on Fraud Pattern Evolution

- **Name-Number pattern** (line ~129-135): Most effective automated detection - catches templated fraud emails
- **Suspicious names list** (line ~27-30): Add names that appear frequently in fraud accounts
- Theme keywords can be expanded in `theme_keywords` dictionary (line ~19-25)
- Major email providers whitelist in `major_providers` list (line ~14-17)
- Fraud patterns evolve - review flagged false positives monthly
- Risk score thresholds may need adjustment based on actual fraud rates
- Monitor SUSPICIOUS NAME PATTERNS section in reports to identify new recurring names
