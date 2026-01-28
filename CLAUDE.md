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
├── scripts/          # Analysis scripts
│   └── email_fraud_detector.py
├── data/            # Place CSV exports here
│   ├── Leads.csv
│   └── Sales.csv
├── reports/         # Generated fraud detection reports
└── docs/            # Additional documentation
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

### Email Fraud Detection
```bash
cd ~/fraud-detection

# Install dependencies (first time only)
pip install -r requirements.txt

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

To adjust fraud detection sensitivity, edit `scripts/email_fraud_detector.py`:

```python
# Line ~105-108: Adjust excessive dots threshold
if dot_count > 3:
    risk_score += 25  # Modify this value

# Line ~111-115: Adjust digit suffix risk
digit_suffix = re.search(r'(\d{4,5})$', username)
if digit_suffix:
    risk_score += 20  # Modify this value

# Line ~129-135: Adjust name-number pattern risk (HIGHEST IMPACT)
name_num_pattern = re.search(r'^([a-z]+)(\d+)([a-z]+)(\d+)', username)
if name_num_pattern:
    risk_score += 40  # Modify this value

# Line ~144-147: Adjust suspicious name risk
if suspicious_found:
    risk_score += 30  # Modify this value

# Line ~27-30: Add/remove suspicious names
self.suspicious_names = [
    'fatima', 'oduwale', 'olatunde', 'muhammed', 'mohammed'
]

# Line ~188-195: Adjust domain concentration threshold
if percentage > 90:  # Change from 90% to be more/less strict
```

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
