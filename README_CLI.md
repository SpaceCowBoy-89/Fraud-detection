# Fraud Detection CLI System

A comprehensive command-line interface for detecting fraud in affiliate marketing accounts with API integration and advanced email pattern detection.

## Features

✅ **Rich CLI Interface** - Beautiful terminal UI with colors, progress bars, and responsive layouts  
✅ **Grouped Menu Structure** - Logical organization (Data, Detection, Analysis, Review, System)  
✅ **Quick Shortcuts** - Single-letter shortcuts for power users (`f`, `r`, `v`, `a`, etc.)  
✅ **Help System** - Press `h` or `?` anytime for help  
✅ **API Integration** - Fetch data directly from affiliate tracking API  
✅ **Advanced Fraud Detection** - Multiple pattern detection algorithms:
   - Name-number patterns (e.g., john43murphy5398@gmail.com)
   - Repeated word patterns (dynamic detection)
   - Scrambled email patterns (improved detection)
   - Written number patterns (e.g., emillytwo@gmail.com)
   - Suspicious name detection
   - Domain concentration analysis
   - POV validation timing
   - Device type analysis
   - Geographic clustering

✅ **Config-Driven Risk Scores** - Adjust all scores in `config.json` without code changes  
✅ **Outcome Tracking** - Record confirmed fraud / false positives  
✅ **Effectiveness Metrics** - Track detection precision over time  
✅ **Database Storage** - SQLite database with proper indexing  
✅ **Unit Tests** - Comprehensive test coverage  

## Installation

### 1. Install Dependencies

```bash
cd /Users/pat/fraud-detection
pip install -r requirements.txt
```

### 2. Configure API Key

First time setup:

```bash
python3 cli_app.py
```

Navigate to **System → Settings** and set your API key.

Or set as environment variable:
```bash
export FRAUD_DETECTION_API_KEY="your_api_key_here"
```

## Usage

### Start the CLI

```bash
# Recommended - New modular CLI (v3.0)
python3 cli_app.py

# Legacy CLI (still works)
python3 cli_fraud_detection.py
```

### Menu Structure

```
📥 DATA
    1. Fetch New Data (f)

🔍 DETECTION
    2. Run Fraud Analysis (r)
    3. View Reports (v)
    4. High-Risk Alerts (a)
    5. Test Single Email (t)

📊 ADVANCED ANALYSIS
    6. Temporal Analysis
    7. Pattern Discovery
    8. Cluster Analysis
    9. Anomaly Detection
   10. Drift Monitoring
   11. Billing Correlations (b)

✅ REVIEW & METRICS
   12. Record Outcomes (o)
   13. Effectiveness Dashboard (e)
   14. Low-Risk Sampling

⚙️ SYSTEM
   15. Dashboard Metrics (d)
   16. Settings (s)
   17. View Logs (l)
   18. Export Reports

    0. Exit
```

### Quick Shortcuts

| Key | Action |
|-----|--------|
| `f` | Fetch new data |
| `r` | Run fraud analysis |
| `v` | View reports |
| `a` | High-risk alerts |
| `t` | Test single email |
| `b` | Billing correlations |
| `o` | Record outcomes |
| `e` | Effectiveness dashboard |
| `d` | Dashboard metrics |
| `s` | Settings |
| `l` | View logs |
| `h` or `?` | Help |
| `0` | Exit |

### Navigation

- **Back**: Press `b` in any submenu to go back
- **Help**: Press `h` or `?` for context-sensitive help
- **Breadcrumbs**: Navigation path shown at top of screens

## Typical Workflow

### Daily Fraud Check

```
1. Start CLI: python3 cli_fraud_detection.py
2. Select Option 1 (Fetch New Data)
   - Choose "Both" (leads + sales)
   - Select "Since last fetch" (incremental)
   - Skip filters (or apply as needed)
3. Select Option 2 (Run Fraud Detection)
   - Choose "New data only"
4. Select Option 6 (Check High-Risk Alerts)
   - Review flagged accounts
   - Create Asana tasks for investigation
5. Select Option 7 (Export Reports)
   - Save for documentation
```

### Weekly Pattern Review

```
1. Select Option 5 (View Dashboard Metrics)
   - Check fraud detection rate trends
2. Select Option 3 (View Reports)
   - Analyze new fraud patterns
   - Identify repeated word clusters
3. Update CLAUDE.md with new patterns discovered
```

## Database Structure

The CLI automatically creates and manages a SQLite database with the following tables:

- **paid** - Paid transactions (sales)
- **free** - Free signups (leads)
- **fraud_results** - Fraud detection analysis results
- **fetch_history** - API fetch tracking

## Configuration

Configuration is stored in `config.json`. All risk scores are now config-driven:

```json
{
  "api_key": "your_api_key",
  "risk_thresholds": {
    "high": 50,
    "medium": 25
  },
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
  "ip_velocity_threshold": 10,
  "whitelisted_affiliates": []
}
```

## Optional Filters Available

### All Data Types
- **webmaster_code** - Filter by affiliate webmaster code
- **email_domain** - Filter by email domain (e.g., gmail.com)
- **campaign** - Filter by campaign ID
- **custom_http_user_agent** - Filter by browser/device user agent

### Leads Only
- **pov_verified** - Filter by email verification status (true/false)
- **site_code** - Filter by specific site code

### Sales Only
- **chargeback_count** - Minimum number of chargebacks
- **credit_count** - Minimum number of credits

## Advanced Features

### Incremental Data Fetching
The CLI tracks the last fetch date and automatically fetches only new data:
```
Select date range: 4. Since last fetch (incremental)
```

### Repeated Word Pattern Detection
The system dynamically finds words that appear >3 times across all emails:
- Finds patterns like "golding" appearing in 25 accounts
- Catches name inversions (hgolding, goldinghenry, etc.)
- No hardcoding needed - adapts to new fraud patterns

### Test Mode
Test any email without fetching data:
```
Option 8: Test Mode
Enter email: suspicious@example.com
→ Instant risk score and analysis
```

## Troubleshooting

### API Key Not Working
```
1. Check API key in config.json
2. Or set environment variable: export FRAUD_DETECTION_API_KEY="key"
3. Test connection in Settings menu
```

### No Data Returned
```
1. Check date range (may be no data in that period)
2. Verify filters aren't too restrictive
3. Check logs: Option 9 (View Logs)
```

### High Memory Usage
```
1. Use incremental fetching instead of large date ranges
2. Analyze in batches (new data only)
3. Consider PostgreSQL for large datasets
```

## File Structure

```
fraud-detection/
├── cli_app.py                # New modular CLI (v3.0) - RECOMMENDED
├── cli_fraud_detection.py    # Legacy CLI interface
├── cli/                      # CLI modules
│   ├── __init__.py
│   ├── helpers.py            # UI helpers, formatters, responsive tables
│   └── menu.py               # Menu system, shortcuts, help
├── database.py               # Database management
├── api_client.py             # API integration
├── config.py                 # Configuration management
├── config.json               # User configuration (created on first run)
├── config.example.json       # Example configuration template
├── affiliate_data.db         # SQLite database
├── scripts/
│   └── email_fraud_detector.py  # Fraud detection engine
├── tests/                    # Unit tests
│   ├── test_email_fraud_detector.py
│   └── test_database.py
├── reports/                  # Generated reports
└── fraud_detection.log       # Activity logs
```

## Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_email_fraud_detector.py -v

# Run with coverage (if pytest-cov installed)
python -m pytest tests/ --cov=. --cov-report=html
```

## Performance Tips

1. **Use Incremental Fetching** - Only fetch new data since last run
2. **Filter Early** - Apply API filters to reduce data transfer
3. **Analyze New Data** - Only analyze unanalyzed records
4. **Index Optimization** - Database indexes are created automatically
5. **Batch Operations** - Process leads and sales separately for large datasets

## Integration with Existing Workflow

This CLI integrates with your existing fraud detection workflow:

1. **Replaces manual CSV exports** - API fetches data automatically
2. **Enhances email pattern detection** - Dynamic pattern discovery
3. **Stores historical data** - Track patterns over time
4. **Generates reports** - Same CSV format as before
5. **Asana integration ready** - Export high-risk accounts for task creation

## Support

For issues or questions:
1. Check logs: `fraud_detection.log`
2. Review CLAUDE.md for fraud patterns
3. Test single emails in Test Mode (Option 8)

## Future Enhancements

- [ ] Real-time webhook integration
- [ ] Asana API integration (auto-create tasks)
- [ ] IP geolocation analysis
- [ ] Card BIN clustering
- [ ] Machine learning model training
- [ ] Web dashboard interface
- [ ] Email notifications for critical alerts
