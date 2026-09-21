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
├── run.py                  # Web app entry point
├── wsgi.py                 # Gunicorn WSGI
├── scheduler.py            # Automated fetch + analyze pipeline
├── scripts/                # Analysis scripts
│   ├── email_fraud_detector.py    # Email pattern detection
│   ├── data_preprocessor.py       # Automatic data cleaning
│   ├── eda_analyzer.py            # Exploratory data analysis
│   └── business_analytics.py      # Business metrics & KPIs
├── dashboard/              # Web dashboard (Flask)
│   ├── app.py             # Flask backend
│   └── templates/
│       └── index.html     # Frontend (HTML/CSS/JS)
├── tests/                  # Unit tests
│   ├── test_email_fraud_detector.py
│   └── test_database.py
├── data/                   # Place CSV exports here
│   ├── Leads.csv
│   └── Sales.csv
├── reports/                # Generated fraud detection reports
│   └── eda_reports/       # EDA analysis exports
├── config.json             # Configuration (risk scores, API key)
├── database.py             # SQLite database management
├── api_client.py           # API integration
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
- **Excessive dots**: >3 dots in email username (+20 risk points)
- **Digit suffix**: 4-5 digits at end of username (+15 risk points)
- **Scrambled patterns**: Low vowel ratio indicating random generation (+35 risk points)
- **Name-Number pattern**: firstname+number+lastname+number structure (+40 risk points)
  - Examples: `john43murphy5398@gmail.com`, `bradley93sanders5984@gmail.com`
- **Suspicious names**: Known fraud-associated names (fatima, oduwale, olatunde, muhammed, mohammed) (+30 risk points)
- **Domain concentration**: >90% traffic from same non-major domain (+20 risk points)
- **Theme clustering**: Related email themes (real estate, construction, crypto, finance) (+15 risk points)
- **Billing gender mismatch** (Paid only): Billing name gender ≠ declared gender (+35 risk points)
  - Example: Billing name "Patricia" but declared gender "man"
  - Uses gender-guesser library to predict gender from first name
  - Only flags high-confidence mismatches (skips androgynous/unknown names)
- **Woman concentration** (Affiliate-level): ≥15% WOMAN registrations from an affiliate (vs. ~0.9% baseline). Flags only the WOMAN accounts from the concentrated source (+25 risk points). Threshold configurable in `build_gender_concentration_map`.
- **Sequential email** (Affiliate-level): Same local-part text stem (letters only, ≥4 chars) + same domain, with **4+ distinct trailing numeric suffixes** within one affiliate (e.g. `maucheesee71@…`, `maucheesee76@…`). Suffixes need not be consecutive. Adds `SEQUENTIAL_EMAIL` (+30 pts, configurable `sequential_email`). Never clusters across affiliates. Dashboard: **Apply sequential email pattern to saved results** re-scores existing `fraud_results` without full re-analysis.

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
- **Credit card connected to multiple accounts** (use "Used By" data, not "Possible Match")
  - Same card used by 3+ accounts = high risk (+35 pts)
  - Same card used by 5+ accounts = fraud ring (+50 pts)
  - Exclude major issuers: Bank of America, JP Morgan Chase, Capital One, Citi
- **Amex card** (Admin API — `cardType`): near-0% baseline on dating sites; any use flagged (+30 pts)
- **Business card** (Admin API — `cardDescription`): inherently suspicious on a dating site; any use flagged (+40 pts)
  - Detected by keywords in `cardDescription`: "business", "corporate", "commercial", "company", "enterprise"
  - No issuer exclusions apply
- **Discover concentration per affiliate** (Admin API — post-enrichment pass):
  - Baseline: ~2% of transactions
  - Threshold: >10% of an affiliate's enriched accounts using Discover
  - Minimum sample: 10 enriched accounts per affiliate (avoids small-sample noise)
  - Flags only the Discover-card accounts from the concentrated affiliate (+20 pts)
  - Configurable via `discover_concentration_threshold` and `discover_concentration_min_sample` in `config.json`
- Transaction clusters from same card issuer (excluding Bank of America, JP Morgan Chase, Capital One, Citi)

**IP Geolocation Signals** (Admin API enrichment — requires GeoIP databases):
- Raw IP mismatch (different IPs) is **not scored** — user may switch from mobile data to WiFi
- Different cities within same state are **not scored**
- **Cross-state IP mismatch**: registration IP state ≠ login IP state (same country) → +15 pts
- **Cross-country IP mismatch**: registration IP country ≠ login IP country → +35 pts
- **Login IP in high-risk country** (configurable list): NG, GH, CI, CM, PH, RO, MD, ID → +30 pts
- **Login IP ≠ CSV geo_country**: login IP resolves to different country than leads CSV geo field → +25 pts
- **Datacenter/cloud IP** (registration or login): AWS, GCP, Azure, DigitalOcean, etc. → +25 pts each
- **VPN/proxy IP** (registration or login): NordVPN, Mullvad, ProtonVPN, etc. → +20 pts each
- GeoIP databases: `data/GeoLite2-City.mmdb` (city/country) and `data/GeoLite2-ASN.mmdb` (ISP/datacenter)
- Download: `python3 scripts/download_geoip.py` (db-ip.com free tier, no account needed, ~75 MB total)

**Profile Behavior Indicators**:
- **No profile image uploaded** = suspicious (bot account)
- **Image uploaded within 30 seconds of registration** = pre-prepared (stolen/stock image)
- Image uploaded 2-10 minutes after registration = likely legitimate
- Use reverse image search (Google Images, TinEye) to detect:
  - Stock photos from Shutterstock, Getty Images
  - Images stolen from other profiles
  - AI-generated faces

## Running Fraud Detection

### Web dashboard (primary)

```bash
cd ~/fraud-detection
pip install -r requirements.txt
python run.py
```

Open http://localhost:5050 — fetch, analyze, review outcomes, EDA, business metrics, ML training.

**Docker:**

```bash
docker compose up -d --build
```

See [docs/OPERATIONS.md](docs/OPERATIONS.md) for **web + scheduler** services, SQLite backups, `/api/health/ready`, and gunicorn.

**Dashboard capabilities:**
- Fetch and analyze from the UI; scheduler for automation
- Config-driven risk scores (`config.json` or Settings)
- Exploratory Data Analysis (Analytics → Data Explorer)
- Business metrics and effectiveness / model performance
- Date range and affiliate/campaign filters
- Supervised ML: train on reviewed outcomes (`POST /api/ml/train`)

## New Features (2026)

### Data Preprocessing (Automatic)
All data is automatically cleaned before fraud detection:
- **Email normalization**: Lowercase, trim whitespace, validate format
- **Disposable email detection**: Flags temp-mail.org, guerrillamail.com, etc.
- **Amount validation**: Detects outliers using Z-score (>3 std devs)
- **Data enrichment**: Adds time-based features (hour, day of week, weekend/night flags)
- **Quality reporting**: Tracks cleaning stats (invalid emails, outliers, etc.)

**Module**: `scripts/data_preprocessor.py`

### Exploratory Data Analysis (EDA)
Comprehensive data exploration and insights:
- **Data Profiling**: Record counts, completeness, missing values, date ranges
- **Distribution Analysis**: Email domains, payout amounts, geographic, time patterns
- **Fraud Correlations**: Fraud rate by domain, amount, country, campaign, hour
- **Quality Checks**: Missing fields, duplicates, outliers, suspicious patterns
- **Outlier Detection**: Statistical outlier flagging with auto-review option

**Access:**
- **Dashboard**: "Data Explorer" tab in Analytics section
- **Export**: JSON format, PDF coming soon

**Module**: `scripts/eda_analyzer.py`

### Business Analytics & KPIs
Track financial impact and ROI:
- **Fraud Loss Prevented**: Total $ saved, trend vs previous period
- **False Positive Rate**: % of flagged accounts that are legitimate
- **Risk Management**: Overall fraud rate, risk distribution, trends
- **Value Metrics**: Protection rate, net value, savings rate (ROI alternatives)
- **Industry Benchmarks**: Compare to dating industry averages (Tinder, Match.com, etc.)
- **Stakeholder Views**: Tailored metrics for Finance, Marketing, Operations

**Key Metrics:**
- **Fraud Loss Prevented**: Confirmed fraud × payout amount
- **Protection Rate**: Fraud prevented / (prevented + losses)
- **False Positive Rate**: FP / Total flagged accounts
- **Overall Fraud Rate**: Confirmed fraud / Total accounts
- **Industry Comparison**: Dating sites average 3.1% fraud rate, 3.5% FP rate

**Access:**
- **Dashboard**: Integrated into Overview tab
- **API**: `/api/business/metrics` for comprehensive metrics

**Module**: `scripts/business_analytics.py`

### Date Range Filtering
Analyze specific time periods:
- **Dashboard**: Date range dropdown in Analysis panel (7/14/30/90 days, custom)
- **Filter by**: Transaction date (`trans_datetime` field)
- **Use case**: Re-analyze January data separately from February

### Account Age Filtering (DUID-based)
Only analyze recent accounts (last 3 months):
- **Reference**: DUID 384046981 = Nov 1, 2025 12:02 AM
- **Filter**: Accounts with DUID < 384046981 are excluded
- **Rationale**: DUIDs increment sequentially by registration date
- **Configurable**: Edit `min_duid_threshold` in `config.json`

### Multi-Select Filtering (Dashboard)
Target specific affiliates and campaigns:
- **Fetch Data**: Select multiple affiliates/campaigns to fetch
- **Analysis**: Analyze only selected affiliate/campaign combinations
- **Combinations**: System handles all permutations (2 affiliates × 2 campaigns = 4 fetches)
- **UI**: Searchable dropdowns with account counts

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
1. **Email validation timestamp endpoints** (highest priority)
2. **Account registration timestamp** (critical for timing analysis)
3. **Billing relationships** - "Used By" data showing accounts sharing same credit card
   - Only confirmed matches (not "Possible Match" fuzzy data)
   - Hashed/tokenized card fingerprint (no raw card numbers)
4. **Admin event logs** - Profile image upload events and timestamps
   - Detect bots (no image) and stolen images (instant upload)
5. Account creation event hooks
6. Scheduled export automation

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
